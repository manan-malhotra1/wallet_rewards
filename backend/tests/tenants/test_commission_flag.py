"""The commission wallet flag is creation-time only (spec D3).

Immutability is the decision that removes backfill-on-flip, teardown of
non-zero balances, and any intermediate `backfill_pending` state. It must be
enforced at the service, not merely hidden in the UI.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.schemas import TenantCreate, TenantUpdateRequest
from app.modules.tenants.service import create_tenant, update_tenant
from app.shared.exceptions import CommissionFlagImmutable


def _create(name: str, *, flag: bool = False) -> TenantCreate:
    """A minimal valid tenant create body."""
    return TenantCreate(
        name=name,
        business_type="wallet",
        base_currency="ZAR",
        commission_wallet_enabled=flag,
    )


@pytest.mark.asyncio
async def test_flag_set_at_creation(db_session: AsyncSession) -> None:
    """The operator opts in when the tenant is created."""
    tenant = await create_tenant(db_session, _create("Commission Co", flag=True))
    assert tenant.commission_wallet_enabled is True


@pytest.mark.asyncio
async def test_flag_defaults_off(db_session: AsyncSession) -> None:
    """Absent means off — no tenant is opted in by accident."""
    tenant = await create_tenant(db_session, _create("Plain Co"))
    assert tenant.commission_wallet_enabled is False


@pytest.mark.asyncio
async def test_flag_cannot_be_turned_on_later(
    db_session: AsyncSession, admin_principal
) -> None:
    """The retrofit path is the script, not the API (D3)."""
    tenant = await create_tenant(db_session, _create("Later Co"))
    with pytest.raises(CommissionFlagImmutable):
        await update_tenant(
            tenant.id,
            TenantUpdateRequest(commission_wallet_enabled=True),
            db_session,
            admin=admin_principal,
        )


@pytest.mark.asyncio
async def test_flag_cannot_be_turned_off_later(
    db_session: AsyncSession, admin_principal
) -> None:
    """Turning it off would strand non-zero commission balances."""
    tenant = await create_tenant(db_session, _create("OnCo", flag=True))
    with pytest.raises(CommissionFlagImmutable):
        await update_tenant(
            tenant.id,
            TenantUpdateRequest(commission_wallet_enabled=False),
            db_session,
            admin=admin_principal,
        )


@pytest.mark.asyncio
async def test_restating_the_current_value_is_allowed(
    db_session: AsyncSession, admin_principal
) -> None:
    """An idempotent PUT that echoes the stored value must not 422."""
    tenant = await create_tenant(db_session, _create("Echo Co", flag=True))
    updated = await update_tenant(
        tenant.id,
        TenantUpdateRequest(name="Echo Co Renamed", commission_wallet_enabled=True),
        db_session,
        admin=admin_principal,
    )
    assert updated.name == "Echo Co Renamed"
    assert updated.commission_wallet_enabled is True


@pytest.mark.asyncio
async def test_update_without_the_field_is_unaffected(
    db_session: AsyncSession, admin_principal
) -> None:
    """Editing other fields must not trip the immutability guard."""
    tenant = await create_tenant(db_session, _create("Rename Co", flag=True))
    updated = await update_tenant(
        tenant.id,
        TenantUpdateRequest(name="Renamed Co"),
        db_session,
        admin=admin_principal,
    )
    assert updated.name == "Renamed Co"
    assert updated.commission_wallet_enabled is True
