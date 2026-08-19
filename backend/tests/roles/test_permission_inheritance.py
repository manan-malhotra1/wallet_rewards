"""Derived services inherit their base service's role grants (story B4.6).

`has_permission` matches `transaction_type` exactly, which meant a derived
service was permitted for nobody until someone added a grant for its exact
code — and there is no admin screen for role permissions, so an operator could
create a variant in the UI and have no way to make it usable. These pin the
resolution order: an explicit grant wins, an explicit denial blocks (including
blocking inheritance), otherwise a derived service falls back to its base.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.service import has_permission
from app.shared.models import (
    Role,
    RolePermission,
    Service,
    Tenant,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio


async def _user_with_role(
    session: AsyncSession, tenant: Tenant, *, role_status: str = "active"
) -> tuple[User, Role]:
    """Create a user holding one role, plus the p2p base and its variant."""
    user = User(tenant_id=tenant.id, user_type="consumer")
    role = Role(tenant_id=tenant.id, name="standard_user", status=role_status)
    session.add_all([user, role])
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.add(
        Service(
            tenant_id=tenant.id,
            code="p2p",
            display_name="Peer-to-Peer",
            kind="base",
            status="active",
        )
    )
    session.add(
        Service(
            tenant_id=tenant.id,
            code="p2p_diaspora",
            display_name="Diaspora Transfer",
            kind="derived",
            base_service_code="p2p",
            status="active",
        )
    )
    await session.commit()
    return user, role


async def test_derived_service_is_permitted_via_its_base_grant(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a grant on the base permits the variant with no row of its own."""
    user, role = await _user_with_role(db_session, test_tenant)
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    await db_session.commit()

    assert await has_permission(db_session, user.id, "p2p") is True
    assert await has_permission(db_session, user.id, "p2p_diaspora") is True


async def test_explicit_denial_on_the_variant_blocks_inheritance(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify `permitted=false` on the variant beats the inherited grant.

    This is the ONLY way to withhold a variant from a role that holds its base,
    so the inherited grant must not resurrect it.
    """
    user, role = await _user_with_role(db_session, test_tenant)
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    db_session.add(
        RolePermission(role_id=role.id, transaction_type="p2p_diaspora", permitted=False)
    )
    await db_session.commit()

    assert await has_permission(db_session, user.id, "p2p") is True
    assert await has_permission(db_session, user.id, "p2p_diaspora") is False


async def test_inheritance_is_one_way(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify granting the variant does NOT grant the base flow.

    Inheritance runs child-from-parent only. If it ran both ways, granting a
    narrow variant would quietly hand over the whole base flow.
    """
    user, role = await _user_with_role(db_session, test_tenant)
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p_diaspora", permitted=True))
    await db_session.commit()

    assert await has_permission(db_session, user.id, "p2p_diaspora") is True
    assert await has_permission(db_session, user.id, "p2p") is False


async def test_inactive_role_grants_nothing_to_inherit(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify an inactive role's base grant is not inherited either.

    `roles.status` is the tier-wide kill switch, so it must switch off the
    variant along with the base.
    """
    user, role = await _user_with_role(db_session, test_tenant, role_status="inactive")
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    await db_session.commit()

    assert await has_permission(db_session, user.id, "p2p") is False
    assert await has_permission(db_session, user.id, "p2p_diaspora") is False


async def test_a_base_service_without_a_grant_is_still_refused(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify inheritance changes nothing for base services (Pay-PRD-0440).

    A base has no `base_service_code`, so there is nothing to fall back to and
    deny-by-default must still hold.
    """
    user, _role = await _user_with_role(db_session, test_tenant)

    assert await has_permission(db_session, user.id, "p2p") is False


async def test_inheritance_does_not_cross_tenants(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a variant cannot borrow a base grant from another tenant.

    The base lookup is scoped through the user's own tenant, so an identically
    named variant elsewhere lends nothing.
    """
    other = Tenant(name="Other-Tenant", business_type="wallet", base_currency="ZAR")
    db_session.add(other)
    await db_session.flush()

    user, role = await _user_with_role(db_session, test_tenant)
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    # A variant of the same name in the OTHER tenant only.
    db_session.add(
        Service(
            tenant_id=other.id,
            code="p2p_offshore",
            display_name="Offshore Transfer",
            kind="derived",
            base_service_code="p2p",
            status="active",
        )
    )
    await db_session.commit()

    # Our user's tenant has no `p2p_offshore`, so there is no base to inherit.
    assert await has_permission(db_session, user.id, "p2p_offshore") is False
