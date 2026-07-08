"""Roles service — CRUD + the authoritative `has_permission` check.

`has_permission(user_id, transaction_type)` is the canonical step 1 of the
payment orchestration sequence (Pay-PRD-0260). It returns True iff the user
holds at least one ACTIVE role granting that transaction_type.

Per Pay-PRD-0440: "A user with no assigned role may not initiate transactions."
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.roles.schemas import (
    AssignRoleRequest,
    CreateRoleRequest,
    SetPermissionRequest,
    UpdateRoleRequest,
)
from app.shared.exceptions import (
    NotAuthorised,
    RoleAlreadyExists,
    RoleNotFound,
    TenantNotFound,
    UserNotFound,
)
from app.shared.models import (
    ROLE_STATUS_ACTIVE,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject when the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


# -----------------------------------------------------------------------------
# Role CRUD
# -----------------------------------------------------------------------------


async def create_role(session: AsyncSession, request: CreateRoleRequest) -> Role:
    """Create a new role in a tenant.

    Args:
        session: Async DB session.
        request: Validated payload.

    Returns:
        The persisted Role.

    Raises:
        TenantNotFound: unknown tenant.
        RoleAlreadyExists: 409 — name already taken in this tenant.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    role = Role(
        tenant_id=request.tenant_id,
        name=request.name,
        description=request.description,
    )
    session.add(role)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RoleAlreadyExists(request.name) from exc
    await session.refresh(role)
    return role


async def list_roles(session: AsyncSession, tenant_id: UUID) -> list[Role]:
    """Tenant-scoped list of all roles."""
    await _assert_tenant_exists(session, tenant_id)
    result = await session.execute(
        select(Role).where(Role.tenant_id == tenant_id).order_by(Role.created_at)
    )
    return list(result.scalars().all())


async def get_role(session: AsyncSession, role_id: UUID, tenant_id: UUID) -> Role:
    """Tenant-scoped lookup."""
    result = await session.execute(
        select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise RoleNotFound()
    return role


async def update_role(
    session: AsyncSession,
    role_id: UUID,
    tenant_id: UUID,
    request: UpdateRoleRequest,
) -> Role:
    """Partial update — description and/or status."""
    role = await get_role(session, role_id, tenant_id)
    if request.description is not None:
        role.description = request.description
    if request.status is not None:
        role.status = request.status
    await session.commit()
    await session.refresh(role)
    return role


# -----------------------------------------------------------------------------
# Permissions
# -----------------------------------------------------------------------------


async def set_permission(
    session: AsyncSession,
    role_id: UUID,
    tenant_id: UUID,
    request: SetPermissionRequest,
) -> RolePermission:
    """Upsert a permission row for (role, transaction_type)."""
    # Tenant-scoped role lookup also serves as 404 guard.
    role = await get_role(session, role_id, tenant_id)

    result = await session.execute(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.transaction_type == request.transaction_type,
        )
    )
    perm = result.scalar_one_or_none()
    if perm is None:
        perm = RolePermission(
            role_id=role.id,
            transaction_type=request.transaction_type,
            permitted=request.permitted,
        )
        session.add(perm)
    else:
        perm.permitted = request.permitted
    await session.commit()
    await session.refresh(perm)
    return perm


async def remove_permission(
    session: AsyncSession,
    role_id: UUID,
    tenant_id: UUID,
    transaction_type: str,
) -> None:
    """Delete a permission row. No-op if absent."""
    role = await get_role(session, role_id, tenant_id)
    result = await session.execute(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.transaction_type == transaction_type,
        )
    )
    perm = result.scalar_one_or_none()
    if perm is not None:
        await session.delete(perm)
        await session.commit()


async def list_permissions(
    session: AsyncSession, role_id: UUID, tenant_id: UUID
) -> list[RolePermission]:
    role = await get_role(session, role_id, tenant_id)
    result = await session.execute(select(RolePermission).where(RolePermission.role_id == role.id))
    return list(result.scalars().all())


# -----------------------------------------------------------------------------
# User-role assignment
# -----------------------------------------------------------------------------


async def _find_user_in_tenant(session: AsyncSession, user_id: UUID, tenant_id: UUID) -> User:
    """Resolve a user_id within the tenant, or 404."""
    result = await session.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()
    return user


async def assign_role_to_user(
    session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    request: AssignRoleRequest,
) -> UserRole:
    """Assign a role to a user. Both must live in the same tenant."""
    user = await _find_user_in_tenant(session, user_id, tenant_id)
    role = await get_role(session, request.role_id, tenant_id)

    # Check for existing assignment — idempotent.
    existing = await session.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    user_role = UserRole(user_id=user.id, role_id=role.id)
    session.add(user_role)
    await session.commit()
    await session.refresh(user_role)
    return user_role


async def remove_role_from_user(
    session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    role_id: UUID,
) -> None:
    """Remove a role from a user. No-op if not assigned."""
    user = await _find_user_in_tenant(session, user_id, tenant_id)
    result = await session.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role_id)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()


async def list_user_roles(session: AsyncSession, user_id: UUID, tenant_id: UUID) -> list[UserRole]:
    user = await _find_user_in_tenant(session, user_id, tenant_id)
    result = await session.execute(select(UserRole).where(UserRole.user_id == user.id))
    return list(result.scalars().all())


# -----------------------------------------------------------------------------
# THE permission check — step 1 of payment orchestration (Pay-PRD-0260)
# -----------------------------------------------------------------------------


async def has_permission(session: AsyncSession, user_id: UUID, transaction_type: str) -> bool:
    """True iff the user holds an ACTIVE role granting transaction_type.

    Pay-PRD-0440: users with no roles cannot transact.
    Pay-PRD-0450: a role must explicitly permit the transaction_type.
    Pay-PRD-0460: this is step 1 of the orchestration sequence.

    Multiple roles: any active role granting the permission is enough.
    """
    stmt = (
        select(RolePermission)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.status == ROLE_STATUS_ACTIVE,
            RolePermission.transaction_type == transaction_type,
            RolePermission.permitted.is_(True),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def require_permission(session: AsyncSession, user_id: UUID, transaction_type: str) -> None:
    """Raise `NotAuthorised` if the user lacks the permission.

    Called as step 1 by `payments/service.p2p_transfer` and
    `redemption/service.initiate_redemption`.
    """
    if not await has_permission(session, user_id, transaction_type):
        raise NotAuthorised(transaction_type)
