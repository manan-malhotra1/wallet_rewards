"""Commission config writes must validate the `user_type` they carry.

Spec §6 requires the check at every point a type is written, config rows
included. A commission written against a typo'd agent type matches nothing at
payout time and silently falls through to the `user_type IS NULL` default row
(spec §11).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import (
    create_commission_config,
    replace_commission_config_for_scope,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import Tenant

pytestmark = pytest.mark.asyncio

BOGUS = "no_such_type"


def _request(tenant: Tenant, user_type: str | None) -> CommissionConfigCreateRequest:
    """Build a minimal cashin/ZAR commission request for the given type scope."""
    return CommissionConfigCreateRequest(
     # Required since spec D8: zero is a decision, not an omission.
     # These tests are about the CHILD leg, so the parent earns nothing.
     parent_fixed_commission=Decimal("0"),
     parent_variable_commission_pct=Decimal("0"),
        tenant_id=tenant.id,
        transaction_type="cashin",
        currency="ZAR",
        user_type=user_type,
        fixed_commission=Decimal("2.00"),
    )


async def test_create_commission_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a commission cannot be written against a nonexistent type."""
    with pytest.raises(AppHTTPException) as exc:
        await create_commission_config(db_session, _request(test_tenant, BOGUS))
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_replace_commission_config_rejects_unknown_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the band-replace path is guarded too, not only create."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_commission_config_for_scope(db_session, [_request(test_tenant, BOGUS)])
    assert exc.value.status_code == 422
    assert exc.value.error_code == "unknown_user_type"


async def test_commission_config_accepts_null_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the `user_type IS NULL` default row — everyone — stays writable."""
    config = await create_commission_config(db_session, _request(test_tenant, None))
    assert config.user_type is None


async def test_commission_config_accepts_a_real_user_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a seeded system type is still accepted (the guard is not a blanket refusal)."""
    config = await create_commission_config(db_session, _request(test_tenant, "agent"))
    assert config.user_type == "agent"
