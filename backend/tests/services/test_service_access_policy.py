"""Per-service access policy: persistence, seed defaults, and tenant scoping.

Covers the two `services` access-policy columns (`allowed_user_types`,
`allowed_channels`) added in migration 0049: that they round-trip through the
ORM, that a fresh provisioning applies the same defaults the migration
backfills (via `SERVICE_POLICY`), and that a per-tenant service query returns
that policy without leaking across tenants.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.schemas import TenantCreate
from app.modules.tenants.service import SERVICE_POLICY, create_tenant
from app.shared.models import Service, Tenant


async def _service(session: AsyncSession, tenant_id, code: str) -> Service:
    """Return the live service with `code` for a tenant."""
    return (
        await session.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.code == code,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_access_policy_columns_persist_arrays(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a service remembers exactly which user types and channels may use it"""
    svc = Service(
        tenant_id=test_tenant.id,
        code=f"custom-{uuid4().hex[:8]}",
        display_name="Custom",
        allowed_user_types=["agent", "super_agent"],
        allowed_channels=["mobile", "ussd"],
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)

    assert svc.allowed_user_types == ["agent", "super_agent"]
    assert svc.allowed_channels == ["mobile", "ussd"]


@pytest.mark.asyncio
async def test_access_policy_defaults_to_unrestricted(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a service with no policy set is stored as unrestricted (NULL)"""
    svc = Service(
        tenant_id=test_tenant.id,
        code=f"open-{uuid4().hex[:8]}",
        display_name="Open",
    )
    db_session.add(svc)
    await db_session.commit()
    await db_session.refresh(svc)

    assert svc.allowed_user_types is None
    assert svc.allowed_channels is None


@pytest.mark.asyncio
async def test_fresh_seed_sets_consumer_policy_for_p2p(
    db_session: AsyncSession,
) -> None:
    """Verify a freshly-provisioned p2p service is limited to consumers on mobile"""
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"policy-tenant-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="USD",
        ),
    )
    p2p = await _service(db_session, tenant.id, "p2p")

    assert p2p.allowed_user_types == ["consumer"]
    assert p2p.allowed_channels == ["mobile"]
    # And it matches the single-source policy the migration also backfills.
    assert (p2p.allowed_user_types, p2p.allowed_channels) == (
        list(SERVICE_POLICY["p2p"][0]),
        list(SERVICE_POLICY["p2p"][1]),
    )


@pytest.mark.asyncio
async def test_fresh_seed_sets_agent_policy_for_cash_in(
    db_session: AsyncSession,
) -> None:
    """Verify a freshly-provisioned cash_in service is limited to agents on mobile"""
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"policy-tenant-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="USD",
        ),
    )
    cash_in = await _service(db_session, tenant.id, "cash_in")

    assert cash_in.allowed_user_types == ["agent", "super_agent"]
    assert cash_in.allowed_channels == ["mobile"]


@pytest.mark.asyncio
async def test_fresh_seed_sets_empty_user_types_for_operator_ops(
    db_session: AsyncSession,
) -> None:
    """Verify operator money ops carry no wallet user type and stay on admin/api"""
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"policy-tenant-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="USD",
        ),
    )
    fund = await _service(db_session, tenant.id, "fund")

    # Empty user-type list = no wallet user singled out; the admin/api channel
    # gate is what confines the operation to the back office.
    assert fund.allowed_user_types == []
    assert fund.allowed_channels == ["admin", "api"]


@pytest.mark.asyncio
async def test_service_policy_query_is_tenant_scoped(
    db_session: AsyncSession,
) -> None:
    """Verify a tenant's service-policy query returns only that tenant's services"""
    tenant_a = await create_tenant(
        db_session,
        TenantCreate(
            name=f"tenant-a-{uuid4().hex[:8]}", business_type="both", base_currency="USD"
        ),
    )
    tenant_b = await create_tenant(
        db_session,
        TenantCreate(
            name=f"tenant-b-{uuid4().hex[:8]}", business_type="both", base_currency="KES"
        ),
    )

    rows = (
        await db_session.execute(
            select(Service.code, Service.allowed_user_types, Service.allowed_channels).where(
                Service.tenant_id == tenant_a.id, Service.deleted_at.is_(None)
            )
        )
    ).all()
    by_code = {code: (uts, chans) for code, uts, chans in rows}

    # Tenant A's policy is present and correct...
    assert by_code["p2p"] == (["consumer"], ["mobile"])
    # ...and the query never returned tenant B's rows (distinct tenant_id).
    b_ids = (
        await db_session.execute(
            select(Service.id).where(Service.tenant_id == tenant_b.id)
        )
    ).scalars().all()
    a_ids = (
        await db_session.execute(
            select(Service.id).where(Service.tenant_id == tenant_a.id)
        )
    ).scalars().all()
    assert set(a_ids).isdisjoint(set(b_ids))
