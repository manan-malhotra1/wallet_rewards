"""Every tenant ships with default end-user roles, and users get one.

Before this, `provision_tenant_defaults` created instruments and services but no
roles, and nothing outside the admin assign-role endpoint ever created a
`user_roles` row. Since `has_permission` denies by default (Pay-PRD-0440), a
fresh tenant's customers could not send money, cash out, redeem or buy airtime —
ever. The dev seed script hand-created a role, which is why it stayed hidden.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.service import has_permission
from app.modules.tenants.service import (
    DEFAULT_ROLE_BY_USER_TYPE,
    default_role_grants,
    provision_tenant_defaults,
)
from app.shared.models import Role, RolePermission, Tenant, User, UserRole

pytestmark = pytest.mark.asyncio


async def _fresh_tenant(session: AsyncSession, name: str = "Fresh-Tenant") -> Tenant:
    """Persist a tenant and provision its defaults, as create_tenant does."""
    tenant = Tenant(name=name, business_type="wallet", base_currency="ZAR")
    session.add(tenant)
    await session.flush()
    await provision_tenant_defaults(session, tenant)
    return tenant


async def test_grants_are_derived_from_the_service_access_policy() -> None:
    """Verify the split puts cash_in on the agent role, not the consumer one.

    `cash_in` in the consumer role would be wrong even though the service gate
    blocks consumers today — widening that policy later would silently hand
    every consumer an agent capability.
    """
    assert default_role_grants("standard_user") == [
        "airtime_recharge",
        "cashout",
        "p2p",
        "redemption",
    ]
    assert default_role_grants("agent") == ["cash_in"]


async def test_provisioning_creates_the_default_roles_with_grants(
    db_session: AsyncSession,
) -> None:
    """Verify a fresh tenant gets both roles, each with its own grants."""
    tenant = await _fresh_tenant(db_session)

    roles = (
        (await db_session.execute(select(Role).where(Role.tenant_id == tenant.id))).scalars().all()
    )
    by_name = {r.name: r for r in roles}
    assert set(by_name) == set(DEFAULT_ROLE_BY_USER_TYPE.values())

    for name, role in by_name.items():
        granted = set(
            (
                await db_session.execute(
                    select(RolePermission.transaction_type).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permitted.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert granted == set(default_role_grants(name))


async def test_provisioning_is_idempotent(db_session: AsyncSession) -> None:
    """Verify re-provisioning duplicates neither roles nor grants.

    `create_tenant` and the seed script both call this, so a second run must be
    a no-op rather than a pile of duplicate permission rows.
    """
    tenant = await _fresh_tenant(db_session)
    await provision_tenant_defaults(db_session, tenant)

    roles = (
        (await db_session.execute(select(Role).where(Role.tenant_id == tenant.id))).scalars().all()
    )
    assert len(roles) == len(set(DEFAULT_ROLE_BY_USER_TYPE.values()))

    for role in roles:
        rows = (
            (
                await db_session.execute(
                    select(RolePermission.transaction_type).where(RolePermission.role_id == role.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == len(set(rows))


async def test_provisioning_tops_up_a_missing_grant(db_session: AsyncSession) -> None:
    """Verify a role that predates a new grant is topped up, not skipped.

    Mirrors what happens when a new role-enforced service ships: re-running
    provisioning should add the missing permission to the existing role.
    """
    tenant = await _fresh_tenant(db_session)
    role = (
        await db_session.execute(
            select(Role).where(Role.tenant_id == tenant.id, Role.name == "standard_user")
        )
    ).scalar_one()
    removed = (
        await db_session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role.id, RolePermission.transaction_type == "p2p"
            )
        )
    ).scalar_one()
    await db_session.delete(removed)
    await db_session.commit()

    await provision_tenant_defaults(db_session, tenant)

    restored = (
        await db_session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role.id, RolePermission.transaction_type == "p2p"
            )
        )
    ).scalar_one_or_none()
    assert restored is not None


async def test_roles_do_not_leak_across_tenants(db_session: AsyncSession) -> None:
    """Verify each tenant gets its own role rows."""
    first = await _fresh_tenant(db_session, "Tenant-One")
    second = await _fresh_tenant(db_session, "Tenant-Two")

    for tenant in (first, second):
        names = (
            (await db_session.execute(select(Role.name).where(Role.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        assert set(names) == set(DEFAULT_ROLE_BY_USER_TYPE.values())


async def test_a_new_consumer_can_transact_but_not_cash_in(
    db_session: AsyncSession,
) -> None:
    """Verify the whole point: a freshly created consumer can actually pay.

    And that the split holds — a consumer does not get the agent's cash_in.
    """
    tenant = await _fresh_tenant(db_session)
    user = User(tenant_id=tenant.id, user_type="consumer")
    db_session.add(user)
    await db_session.flush()

    from app.modules.roles.service import assign_default_role

    await assign_default_role(db_session, user)
    await db_session.commit()

    assert await has_permission(db_session, user.id, "p2p") is True
    assert await has_permission(db_session, user.id, "cashout") is True
    assert await has_permission(db_session, user.id, "cash_in") is False


async def test_a_new_agent_gets_cash_in(db_session: AsyncSession) -> None:
    """Verify agents and super_agents land on the agent role."""
    tenant = await _fresh_tenant(db_session)
    from app.modules.roles.service import assign_default_role

    for user_type in ("agent", "super_agent"):
        user = User(tenant_id=tenant.id, user_type=user_type)
        db_session.add(user)
        await db_session.flush()
        await assign_default_role(db_session, user)
        await db_session.commit()

        assert await has_permission(db_session, user.id, "cash_in") is True


async def test_a_merchant_gets_no_role(db_session: AsyncSession) -> None:
    """Verify merchants get no default role — their flow uses API-key auth.

    Assigning them a role would imply a control that `merchant_cashin` never
    consults.
    """
    tenant = await _fresh_tenant(db_session)
    user = User(tenant_id=tenant.id, user_type="merchant")
    db_session.add(user)
    await db_session.flush()

    from app.modules.roles.service import assign_default_role

    await assign_default_role(db_session, user)
    await db_session.commit()

    assigned = (
        (await db_session.execute(select(UserRole).where(UserRole.user_id == user.id)))
        .scalars()
        .all()
    )
    assert assigned == []


async def test_a_tenant_without_defaults_still_allows_user_creation(
    db_session: AsyncSession,
) -> None:
    """Verify a missing default role does not break user creation.

    Tenants provisioned before this shipped have no default roles; creating a
    user there must still succeed (unable to transact, which the Services
    readiness signal surfaces) rather than 500.
    """
    tenant = Tenant(name="Legacy-Tenant", business_type="wallet", base_currency="ZAR")
    db_session.add(tenant)
    await db_session.flush()
    user = User(tenant_id=tenant.id, user_type="consumer")
    db_session.add(user)
    await db_session.flush()

    from app.modules.roles.service import assign_default_role

    await assign_default_role(db_session, user)
    await db_session.commit()

    assert await has_permission(db_session, user.id, "p2p") is False
