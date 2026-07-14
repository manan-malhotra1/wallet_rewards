"""Tests for the fail-closed service gate (Epic 23, Story 23.1).

`require_pricing_and_limits` enforces that BOTH a pricing config and a limit
config resolve for the acting user's type before a service may run — but only
when the tenant's `require_config_to_transact` flag is on. When the flag is
off the gate is a no-op, preserving the legacy fail-open behaviour.
"""

from decimal import Decimal

import pytest

from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import create_limit_config
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import (
    create_pricing_config,
    require_pricing_and_limits,
)
from app.shared.exceptions import ServiceNotConfigured
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

pytestmark = pytest.mark.asyncio

SERVICE = "p2p"
CURRENCY = "ZAR"


async def _seed_pricing(session, tenant_id) -> None:
    """Create a default (all-user-types) p2p pricing config."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type=SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=CURRENCY,
            fixed_fee=Decimal("5"),
        ),
    )


async def _seed_limit(session, tenant_id) -> None:
    """Create a default (all-user-types) p2p limit config."""
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type=SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=CURRENCY,
            daily_count_cap=10,
        ),
    )


async def _gate(session, tenant_id, user_id) -> bool:
    return await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=SERVICE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=CURRENCY,
        user_id=user_id,
    )


async def test_gate_is_noop_when_flag_off(db_session, test_tenant, test_user):
    """Flag off + no configs → no raise, returns False (legacy pass-through)."""
    assert test_tenant.require_config_to_transact is False
    result = await _gate(db_session, test_tenant.id, test_user.id)
    assert result is False


async def test_gate_passes_when_both_configs_present(db_session, test_tenant, test_user):
    """Flag on + pricing AND limit config → returns True, no raise."""
    test_tenant.require_config_to_transact = True
    await _seed_pricing(db_session, test_tenant.id)
    await _seed_limit(db_session, test_tenant.id)
    await db_session.commit()

    result = await _gate(db_session, test_tenant.id, test_user.id)
    assert result is True


async def test_gate_raises_when_pricing_missing(db_session, test_tenant, test_user):
    """Flag on + limit but no pricing → ServiceNotConfigured naming service."""
    test_tenant.require_config_to_transact = True
    await _seed_limit(db_session, test_tenant.id)
    await db_session.commit()

    with pytest.raises(ServiceNotConfigured) as exc:
        await _gate(db_session, test_tenant.id, test_user.id)
    assert SERVICE in exc.value.message


async def test_gate_raises_when_limits_missing(db_session, test_tenant, test_user):
    """Flag on + pricing but no limit → ServiceNotConfigured naming service."""
    test_tenant.require_config_to_transact = True
    await _seed_pricing(db_session, test_tenant.id)
    await db_session.commit()

    with pytest.raises(ServiceNotConfigured) as exc:
        await _gate(db_session, test_tenant.id, test_user.id)
    assert SERVICE in exc.value.message


async def test_gate_names_user_type_in_error(db_session, test_tenant, test_user):
    """The 422 message names the resolved user_type (default 'consumer')."""
    test_tenant.require_config_to_transact = True
    await db_session.commit()

    with pytest.raises(ServiceNotConfigured) as exc:
        await _gate(db_session, test_tenant.id, test_user.id)
    assert "consumer" in exc.value.message


async def test_gate_ignores_configs_for_a_different_user_type(db_session, test_tenant, test_user):
    """Flag on + configs scoped ONLY to a different user_type → still raises.

    `test_user` resolves to 'consumer'; configs seeded for 'agent' must not
    satisfy the gate (no NULL-default row exists).
    """
    test_tenant.require_config_to_transact = True
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type=SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=CURRENCY,
            user_type="agent",
            fixed_fee=Decimal("5"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type=SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=CURRENCY,
            user_type="agent",
            daily_count_cap=10,
        ),
    )
    await db_session.commit()

    with pytest.raises(ServiceNotConfigured):
        await _gate(db_session, test_tenant.id, test_user.id)


async def test_gate_matches_typed_config_for_matching_user_type(db_session, test_tenant, test_user):
    """Flag on + configs scoped to the caller's own user_type → passes."""
    test_tenant.require_config_to_transact = True
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type=SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=CURRENCY,
            user_type="consumer",
            fixed_fee=Decimal("5"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type=SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=CURRENCY,
            user_type="consumer",
            daily_count_cap=10,
        ),
    )
    await db_session.commit()

    assert await _gate(db_session, test_tenant.id, test_user.id) is True
