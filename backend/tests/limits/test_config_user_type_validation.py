"""Limit + wallet-limit config writes must validate the `user_type` they carry.

Spec §6 requires the check at every point a type is written, config rows
included. Without it a limit written against a typo'd type matches nothing at
enforcement time and the transaction silently falls through to the
`user_type IS NULL` default row (spec §11) — a saved config that does nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.schemas import LimitConfigCreateRequest, WalletLimitConfigCreateRequest
from app.modules.limits.service import (
    create_limit_config,
    create_wallet_limit_config,
    replace_limit_config_for_scope,
    replace_wallet_limit_config_for_scope,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Tenant

pytestmark = pytest.mark.asyncio

BOGUS = "no_such_type"


def _limit_request(tenant: Tenant, user_type: str | None) -> LimitConfigCreateRequest:
    """Build a minimal p2p/ZAR limit request for the given type scope."""
    return LimitConfigCreateRequest(
        tenant_id=tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user_type=user_type,
        max_amount=Decimal("100"),
    )


def _wallet_request(tenant: Tenant, user_type: str | None) -> WalletLimitConfigCreateRequest:
    """Build a minimal ZAR wallet-limit request for the given type scope."""
    return WalletLimitConfigCreateRequest(
        tenant_id=tenant.id,
        currency="ZAR",
        user_type=user_type,
        max_balance=Decimal("5000"),
    )


async def test_create_limit_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a limit config cannot be written against a nonexistent type."""
    with pytest.raises(AppHTTPException) as exc:
        await create_limit_config(db_session, _limit_request(test_tenant, BOGUS))
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_replace_limit_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the update path is guarded too, not only create."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_limit_config_for_scope(db_session, [_limit_request(test_tenant, BOGUS)])
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_limit_config_accepts_null_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the `user_type IS NULL` default row — everyone — stays writable."""
    config = await create_limit_config(db_session, _limit_request(test_tenant, None))
    assert config.user_type is None


async def test_limit_config_accepts_a_real_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a seeded system type is still accepted (the guard is not a blanket refusal)."""
    config = await create_limit_config(db_session, _limit_request(test_tenant, "agent"))
    assert config.user_type == "agent"


async def test_create_wallet_limit_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify wallet-limit configs carry the same guard as transaction limits."""
    with pytest.raises(AppHTTPException) as exc:
        await create_wallet_limit_config(db_session, _wallet_request(test_tenant, BOGUS))
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_replace_wallet_limit_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the wallet-limit update path is guarded too."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_wallet_limit_config_for_scope(
            db_session, [_wallet_request(test_tenant, BOGUS)]
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_wallet_limit_config_accepts_null_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the wallet-limit default row stays writable."""
    config = await create_wallet_limit_config(db_session, _wallet_request(test_tenant, None))
    assert config.user_type is None
