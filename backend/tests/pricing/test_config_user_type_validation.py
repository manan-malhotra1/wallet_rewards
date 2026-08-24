"""Pricing config writes must validate the `user_type` they carry.

Spec §6 requires the check at every point a type is written, config rows
included. A price written against a typo'd type matches nothing at quote time
and silently falls through to the `user_type IS NULL` default row (spec §11).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config, replace_pricing_config_for_scope
from app.shared.exceptions import AppHTTPException
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Tenant

pytestmark = pytest.mark.asyncio

BOGUS = "no_such_type"


def _request(tenant: Tenant, user_type: str | None) -> PricingConfigCreateRequest:
    """Build a minimal p2p/ZAR pricing request for the given type scope."""
    return PricingConfigCreateRequest(
        tenant_id=tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user_type=user_type,
        fixed_fee=Decimal("1.50"),
    )


async def test_create_pricing_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a fee cannot be priced against a nonexistent type."""
    with pytest.raises(AppHTTPException) as exc:
        await create_pricing_config(db_session, _request(test_tenant, BOGUS))
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_replace_pricing_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the band-replace path is guarded too, not only create."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_pricing_config_for_scope(db_session, [_request(test_tenant, BOGUS)])
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_pricing_config_accepts_null_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the `user_type IS NULL` default row — everyone — stays writable."""
    config = await create_pricing_config(db_session, _request(test_tenant, None))
    assert config.user_type is None


async def test_pricing_config_accepts_a_real_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a seeded system type is still accepted (the guard is not a blanket refusal)."""
    config = await create_pricing_config(db_session, _request(test_tenant, "agent"))
    assert config.user_type == "agent"
