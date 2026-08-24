"""A custom user type must be priceable and cappable end-to-end.

The point of configurable user types is that an operator creates a type and
then prices and limits it. Four config tables carried static CHECK constraints
pinning `user_type` to the five hardcoded system codes long after migration
0061 dropped the equivalent CHECK on `users`, so every one of those writes was
rejected by the database — and rejected *misleadingly*: `create_*_config` maps
`IntegrityError` to a 409 "config already exists", so the operator was told
their config collided when in fact the type was refused.

Migration 0064 drops the four CHECKs; the guarantee they provided now lives in
`assert_optional_user_type_valid` (spec §6), which can see runtime data a static
allowlist cannot. These tests pin both halves of that trade:

- the four writes against a custom type persist and read back (the feature), and
- a genuine duplicate still returns 409 while a bogus type returns 422
  `unknown_user_type` (the two outcomes the CHECK made indistinguishable).

Every persistence assertion reads back through a SEPARATE session opened from
`session_factory`: all four create paths commit, and only an independent session
proves the row reached the database rather than the writing session's identity
map.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import create_commission_config
from app.modules.limits.schemas import LimitConfigCreateRequest, WalletLimitConfigCreateRequest
from app.modules.limits.service import create_limit_config, create_wallet_limit_config
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    CommissionConfig,
    LimitConfig,
    PricingConfig,
    Tenant,
    WalletLimitConfig,
)

pytestmark = pytest.mark.asyncio

# A code that is not one of the five seeded system types, so it would have been
# rejected by every dropped CHECK.
CUSTOM = "distributor"
BOGUS = "no_such_type"


async def _make_custom_type(session: AsyncSession, tenant: Tenant) -> str:
    """Create an active, tenant-owned type that no static allowlist knows about.

    Args:
        session: The writing session.
        tenant: The tenant that owns the new type.

    Returns:
        The new type's code, ready to be used as a config scope.
    """
    created = await create_user_type(
        session,
        UserTypeCreateRequest(
            tenant_id=tenant.id,
            code=CUSTOM,
            label="Distributor",
            category_code="retail",
        ),
    )
    assert created.code == CUSTOM
    assert created.is_system is False
    return created.code


def _limit_request(tenant: Tenant, user_type: str) -> LimitConfigCreateRequest:
    """Build a p2p/ZAR transaction-limit request scoped to `user_type`."""
    return LimitConfigCreateRequest(
        tenant_id=tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user_type=user_type,
        max_amount=Decimal("2500"),
    )


def _wallet_limit_request(tenant: Tenant, user_type: str) -> WalletLimitConfigCreateRequest:
    """Build a ZAR wallet-limit request scoped to `user_type`."""
    return WalletLimitConfigCreateRequest(
        tenant_id=tenant.id,
        currency="ZAR",
        user_type=user_type,
        max_balance=Decimal("90000"),
    )


def _pricing_request(tenant: Tenant, user_type: str) -> PricingConfigCreateRequest:
    """Build a p2p/ZAR pricing request scoped to `user_type`."""
    return PricingConfigCreateRequest(
        tenant_id=tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user_type=user_type,
        fixed_fee=Decimal("3.50"),
    )


def _commission_request(tenant: Tenant, user_type: str) -> CommissionConfigCreateRequest:
    """Build a cashin/ZAR commission request scoped to `user_type`."""
    return CommissionConfigCreateRequest(
        tenant_id=tenant.id,
        transaction_type="cashin",
        currency="ZAR",
        user_type=user_type,
        fixed_commission=Decimal("4.25"),
    )


async def _committed_user_types(
    factory: async_sessionmaker[AsyncSession], model: type, config_id: UUID
) -> str | None:
    """Read one config row back through a fresh session, seeing only committed rows.

    Args:
        factory: The test session factory, bound to the same test database.
        model: The config ORM class to query.
        config_id: The primary key written by the service.

    Returns:
        The persisted `user_type`, or None if the row never reached the database.
    """
    async with factory() as other:
        row = await other.get(model, config_id)
        return None if row is None else row.user_type


async def test_custom_user_type_can_be_limited_priced_and_paid_commission(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify all four config tables accept a freshly created custom type.

    This is the whole feature in one path: create the type, then cap it, cap its
    wallet, price it and set its commission. Before migration 0064 each write
    tripped a static CHECK and surfaced as a bogus 409.
    """
    code = await _make_custom_type(db_session, test_tenant)

    limit = await create_limit_config(db_session, _limit_request(test_tenant, code))
    wallet_limit = await create_wallet_limit_config(
        db_session, _wallet_limit_request(test_tenant, code)
    )
    pricing = await create_pricing_config(db_session, _pricing_request(test_tenant, code))
    commission = await create_commission_config(db_session, _commission_request(test_tenant, code))

    assert limit.user_type == code
    assert wallet_limit.user_type == code
    assert pricing.user_type == code
    assert commission.user_type == code

    # Read back through an independent session — the create paths commit.
    assert await _committed_user_types(session_factory, LimitConfig, limit.id) == code
    assert await _committed_user_types(session_factory, WalletLimitConfig, wallet_limit.id) == code
    assert await _committed_user_types(session_factory, PricingConfig, pricing.id) == code
    assert await _committed_user_types(session_factory, CommissionConfig, commission.id) == code


async def test_custom_type_config_values_read_back_intact(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the persisted rows carry the configured amounts, not just the type.

    A row that stored the custom type but dropped its caps would satisfy the
    scope assertions above and still be useless to the operator.
    """
    code = await _make_custom_type(db_session, test_tenant)

    await create_limit_config(db_session, _limit_request(test_tenant, code))
    await create_wallet_limit_config(db_session, _wallet_limit_request(test_tenant, code))
    await create_pricing_config(db_session, _pricing_request(test_tenant, code))
    await create_commission_config(db_session, _commission_request(test_tenant, code))

    async with session_factory() as other:
        limit = (
            await other.execute(select(LimitConfig).where(LimitConfig.user_type == code))
        ).scalar_one()
        wallet_limit = (
            await other.execute(
                select(WalletLimitConfig).where(WalletLimitConfig.user_type == code)
            )
        ).scalar_one()
        pricing = (
            await other.execute(select(PricingConfig).where(PricingConfig.user_type == code))
        ).scalar_one()
        commission = (
            await other.execute(select(CommissionConfig).where(CommissionConfig.user_type == code))
        ).scalar_one()

    assert limit.max_amount == Decimal("2500")
    assert wallet_limit.max_balance == Decimal("90000")
    assert pricing.fixed_fee == Decimal("3.50")
    assert commission.fixed_commission == Decimal("4.25")


@pytest.mark.parametrize(
    ("create_fn", "build_request", "error_code"),
    [
        (create_limit_config, _limit_request, "limit_config_already_exists"),
        (create_wallet_limit_config, _wallet_limit_request, "wallet_limit_config_already_exists"),
        (create_pricing_config, _pricing_request, "pricing_config_already_exists"),
        (create_commission_config, _commission_request, "commission_config_already_exists"),
    ],
)
async def test_duplicate_custom_type_config_still_conflicts(
    db_session: AsyncSession,
    test_tenant: Tenant,
    create_fn: object,
    build_request: object,
    error_code: str,
) -> None:
    """Verify 409 still means what it says: this exact scope is already taken.

    The dropped CHECK made 409 ambiguous — it fired both for a real collision
    and for a refused type. Writing the same scope twice must still collide.
    """
    code = await _make_custom_type(db_session, test_tenant)
    await create_fn(db_session, build_request(test_tenant, code))  # type: ignore[operator]

    with pytest.raises(AppHTTPException) as exc:
        await create_fn(db_session, build_request(test_tenant, code))  # type: ignore[operator]
    assert exc.value.status_code == 409
    assert exc.value.error_code == error_code


@pytest.mark.parametrize(
    ("create_fn", "build_request"),
    [
        (create_limit_config, _limit_request),
        (create_wallet_limit_config, _wallet_limit_request),
        (create_pricing_config, _pricing_request),
        (create_commission_config, _commission_request),
    ],
)
async def test_bogus_user_type_config_is_422_not_409(
    db_session: AsyncSession,
    test_tenant: Tenant,
    create_fn: object,
    build_request: object,
) -> None:
    """Verify an unresolvable type is reported as such, not as a phantom collision.

    The other half of the trade in spec §11: the static allowlist is gone, so
    `assert_optional_user_type_valid` is the only thing standing between a typo
    and a config row that silently never matches.
    """
    with pytest.raises(AppHTTPException) as exc:
        await create_fn(db_session, build_request(test_tenant, BOGUS))  # type: ignore[operator]
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"
