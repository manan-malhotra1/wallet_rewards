"""Roles service — CRUD + the authoritative `has_permission` check.

`has_permission(user_id, transaction_type)` is the canonical step 1 of the
payment orchestration sequence (Pay-PRD-0260). It returns True iff the user
holds at least one ACTIVE role granting that transaction_type, where a DERIVED
service also counts its base service's grants (story B4.6).

Per Pay-PRD-0440: "A user with no assigned role may not initiate transactions."
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
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
    Service,
    Tenant,
    User,
    UserRole,
)

log = structlog.get_logger(__name__)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject when the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


def _role_snapshot(role: Role) -> dict[str, str | None]:
    """JSONB-friendly snapshot of a role's auditable fields."""
    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description,
        "status": role.status,
    }


def _permission_snapshot(perm: RolePermission) -> dict[str, str | bool]:
    """JSONB-friendly snapshot of a (role, transaction_type) permission."""
    return {
        "role_id": str(perm.role_id),
        "transaction_type": perm.transaction_type,
        "permitted": perm.permitted,
    }


def _binding_snapshot(binding: UserRole) -> dict[str, str]:
    """JSONB-friendly snapshot of a user-role assignment."""
    return {
        "id": str(binding.id),
        "user_id": str(binding.user_id),
        "role_id": str(binding.role_id),
    }


# -----------------------------------------------------------------------------
# Role CRUD
# -----------------------------------------------------------------------------


async def create_role(
    session: AsyncSession,
    request: CreateRoleRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Role:
    """Create a new role in a tenant.

    Args:
        session: Async DB session.
        request: Validated payload.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP (audit context).

    Returns:
        The persisted Role.

    Raises:
        TenantNotFound: unknown tenant.
        RoleAlreadyExists: 409 — name already taken in this tenant.

    Side effects:
        Writes a `role.created` audit_log row, committed atomically with the
        role insert (NFR-0250).
    """
    await _assert_tenant_exists(session, request.tenant_id)
    role = Role(
        tenant_id=request.tenant_id,
        name=request.name,
        description=request.description,
    )
    session.add(role)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise RoleAlreadyExists(request.name) from exc
    record_audit_for_admin(
        session,
        admin,
        tenant_id=request.tenant_id,
        action="role.created",
        entity_type="role",
        entity_id=str(role.id),
        after_state=_role_snapshot(role),
        ip_address=ip_address,
    )
    await session.commit()
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
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Role:
    """Partial update — description and/or status.

    Side effects:
        Writes a `role.updated` audit_log row (before/after snapshot),
        committed atomically with the change (NFR-0250).
    """
    role = await get_role(session, role_id, tenant_id)
    before = _role_snapshot(role)
    if request.description is not None:
        role.description = request.description
    if request.status is not None:
        role.status = request.status
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="role.updated",
        entity_type="role",
        entity_id=str(role.id),
        before_state=before,
        after_state=_role_snapshot(role),
        ip_address=ip_address,
    )
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
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> RolePermission:
    """Upsert a permission row for (role, transaction_type).

    Side effects:
        Writes a `role.permission_granted` audit_log row (before/after snapshot),
        committed atomically with the upsert (NFR-0250). Authorization edits
        govern who may move money, so this write is mandatory.
    """
    # Tenant-scoped role lookup also serves as 404 guard.
    role = await get_role(session, role_id, tenant_id)

    result = await session.execute(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.transaction_type == request.transaction_type,
        )
    )
    perm = result.scalar_one_or_none()
    before = _permission_snapshot(perm) if perm is not None else None
    if perm is None:
        perm = RolePermission(
            role_id=role.id,
            transaction_type=request.transaction_type,
            permitted=request.permitted,
        )
        session.add(perm)
        await session.flush()
    else:
        perm.permitted = request.permitted
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="role.permission_granted",
        entity_type="role",
        entity_id=str(role.id),
        before_state=before,
        after_state=_permission_snapshot(perm),
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(perm)
    return perm


async def remove_permission(
    session: AsyncSession,
    role_id: UUID,
    tenant_id: UUID,
    transaction_type: str,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> None:
    """Delete a permission row. No-op if absent.

    Side effects:
        When a row is actually deleted, writes a `role.permission_revoked`
        audit_log row (before-state snapshot), committed atomically with the
        delete (NFR-0250). A no-op removal writes nothing.
    """
    role = await get_role(session, role_id, tenant_id)
    result = await session.execute(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.transaction_type == transaction_type,
        )
    )
    perm = result.scalar_one_or_none()
    if perm is not None:
        before = _permission_snapshot(perm)
        await session.delete(perm)
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="role.permission_revoked",
            entity_type="role",
            entity_id=str(role.id),
            before_state=before,
            ip_address=ip_address,
        )
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
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> UserRole:
    """Assign a role to a user. Both must live in the same tenant.

    Side effects:
        When a NEW binding is created, writes a `user.role_assigned` audit_log
        row (entity_type `user_role`), committed atomically with the insert
        (NFR-0250). An idempotent re-assignment (binding already present)
        writes nothing.
    """
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
    await session.flush()
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="user.role_assigned",
        entity_type="user_role",
        entity_id=str(user_role.id),
        after_state=_binding_snapshot(user_role),
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(user_role)
    return user_role


async def remove_role_from_user(
    session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    role_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> None:
    """Remove a role from a user. No-op if not assigned.

    Side effects:
        When a binding is actually removed, writes a `user.role_removed`
        audit_log row (entity_type `user_role`, before-state snapshot),
        committed atomically with the delete (NFR-0250). A no-op removal
        writes nothing.
    """
    user = await _find_user_in_tenant(session, user_id, tenant_id)
    result = await session.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role_id)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        before = _binding_snapshot(row)
        await session.delete(row)
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="user.role_removed",
            entity_type="user_role",
            entity_id=before["id"],
            before_state=before,
            ip_address=ip_address,
        )
        await session.commit()


async def list_user_roles(session: AsyncSession, user_id: UUID, tenant_id: UUID) -> list[UserRole]:
    user = await _find_user_in_tenant(session, user_id, tenant_id)
    result = await session.execute(select(UserRole).where(UserRole.user_id == user.id))
    return list(result.scalars().all())


# -----------------------------------------------------------------------------
# THE permission check — step 1 of payment orchestration (Pay-PRD-0260)
# -----------------------------------------------------------------------------


async def assign_default_role(session: AsyncSession, user: User) -> None:
    """Give a newly created user the default role for their user_type.

    Nothing else in the platform ever created a `user_roles` row, so before this
    a user created through any path held NO role — and `has_permission` denies by
    default (Pay-PRD-0440), meaning they could not send money, cash out, redeem
    or buy airtime. Ever. Only the dev seed script hand-assigned a role, which is
    exactly why the gap went unnoticed.

    Deny-by-default is preserved where it means something: this grants only the
    role the tenant was provisioned with for that user_type, and every other
    guardrail (service access policy, limits, pricing, balance caps, the admin
    access lock) still applies untouched. Merchant user types get no role and
    need none — their only flow authenticates by API key.

    Silently does nothing when the tenant has no such role (a tenant provisioned
    before this shipped): a missing default must not break user creation, and
    the readiness signal on the Services page already surfaces the gap.

    Side effects:
        Inserts one `user_roles` row. Does NOT commit — the caller does.
    """
    from app.modules.tenants.service import DEFAULT_ROLE_BY_USER_TYPE

    role_name = DEFAULT_ROLE_BY_USER_TYPE.get(user.user_type)
    if role_name is None:
        return

    role = (
        await session.execute(
            select(Role).where(Role.tenant_id == user.tenant_id, Role.name == role_name)
        )
    ).scalar_one_or_none()
    if role is None:
        log.warning(
            "default_role_missing_for_tenant",
            tenant_id=str(user.tenant_id),
            user_type=user.user_type,
            role_name=role_name,
        )
        return

    session.add(UserRole(user_id=user.id, role_id=role.id))


async def _permitted_flags(
    session: AsyncSession, user_id: UUID, transaction_type: str
) -> set[bool]:
    """Return the `permitted` values on the user's ACTIVE roles for one code.

    Empty set means no role mentions the code at all — which is different from
    a role mentioning it with `permitted=false`, and the two lead to different
    answers once inheritance is in play (see `has_permission`).
    """
    stmt = (
        select(RolePermission.permitted)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.status == ROLE_STATUS_ACTIVE,
            RolePermission.transaction_type == transaction_type,
        )
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


async def _base_code_of_derived(
    session: AsyncSession, user_id: UUID, transaction_type: str
) -> str | None:
    """Return the base code if this code is a derived service in the user's tenant.

    Tenant-scoped through the user rather than by a passed-in tenant_id, so a
    derived service in one tenant can never lend its base's grants to a user in
    another. Returns None for a base service, an unknown code, or a
    soft-deleted row — each of which means "no inheritance to apply".
    """
    stmt = (
        select(Service.base_service_code)
        .join(User, User.tenant_id == Service.tenant_id)
        .where(
            User.id == user_id,
            Service.code == transaction_type,
            Service.kind == "derived",
            Service.deleted_at.is_(None),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def has_permission(session: AsyncSession, user_id: UUID, transaction_type: str) -> bool:
    """True iff the user holds an ACTIVE role granting transaction_type.

    Pay-PRD-0440: users with no roles cannot transact.
    Pay-PRD-0450: a role must explicitly permit the transaction_type.
    Pay-PRD-0460: this is step 1 of the orchestration sequence.

    Multiple roles: any active role granting the permission is enough.

    DERIVED SERVICES INHERIT their base's grants (story B4.6). A derived service
    is a renamed, re-priced alias of one base flow, so a role that may perform
    the base flow may perform the variant; without inheritance an operator could
    create a variant in the admin UI but never make it usable, because there is
    no admin screen for role permissions. Resolution order:

      1. an explicit `permitted=true` row for this code wins outright;
      2. otherwise an explicit `permitted=false` row for this code DENIES, and
         blocks inheritance — this is the only way to withhold a variant from a
         role that holds its base, so it must beat the inherited grant;
      3. otherwise, for a derived service, the base's grants decide;
      4. otherwise denied.

    Note what inheritance does NOT do: it never grants a base flow because a
    variant was granted (inheritance is one-way, child from parent), and it
    never widens WHO may use a service — `services.allowed_user_types` /
    `allowed_channels` are enforced separately and are narrowing-only.

    The common case (a base code with a grant) still costs exactly one query;
    the extra lookups only happen when the first query finds no grant.
    """
    flags = await _permitted_flags(session, user_id, transaction_type)
    if True in flags:
        return True
    if flags:
        # Only explicit denials — an operator said "not this one", so do not let
        # the base's grant resurrect it.
        return False

    base_code = await _base_code_of_derived(session, user_id, transaction_type)
    if base_code is None:
        return False
    return True in await _permitted_flags(session, user_id, base_code)


async def require_permission(session: AsyncSession, user_id: UUID, transaction_type: str) -> None:
    """Raise `NotAuthorised` if the user lacks the permission.

    Called as step 1 by `payments/service.p2p_transfer` and
    `redemption/service.initiate_redemption`.
    """
    if not await has_permission(session, user_id, transaction_type):
        raise NotAuthorised(transaction_type)
