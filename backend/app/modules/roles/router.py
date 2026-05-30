"""Roles & Permissions FastAPI router.

Admin-only endpoints (gated by `platform-admin` Keycloak realm role from
Phase F.1). Manages per-tenant roles, role permissions, and user-role
assignments.

Endpoints:
  POST   /api/v1/roles                              create role
  GET    /api/v1/roles?tenant_id=                   list roles
  GET    /api/v1/roles/{role_id}?tenant_id=         get role
  PATCH  /api/v1/roles/{role_id}                    update role
  POST   /api/v1/roles/{role_id}/permissions        set permission
  DELETE /api/v1/roles/{role_id}/permissions/{txn_type}  remove permission
  GET    /api/v1/roles/{role_id}/permissions        list permissions
  POST   /api/v1/users/{user_id}/roles              assign role
  DELETE /api/v1/users/{user_id}/roles/{role_id}    remove role
  GET    /api/v1/users/{user_id}/roles              list user roles
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.roles.schemas import (
    AssignRoleRequest,
    CreateRoleRequest,
    RoleOut,
    RolePermissionOut,
    SetPermissionRequest,
    UpdateRoleRequest,
    UserRoleOut,
)
from app.modules.roles.service import (
    assign_role_to_user,
    create_role,
    get_role,
    list_permissions,
    list_roles,
    list_user_roles,
    remove_permission,
    remove_role_from_user,
    set_permission,
    update_role,
)

router = APIRouter(prefix="/api/v1", tags=["roles"])

# Role CRUD requires platform-admin.
_admin_only = Depends(require_admin_role("platform-admin"))


@router.post("/roles", response_model=RoleOut, status_code=201)
async def post_role(
    request: CreateRoleRequest,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> RoleOut:
    """Create a role in a tenant. Admin only."""
    _ = admin
    role = await create_role(session, request)
    return RoleOut.model_validate(role)


@router.get("/roles", response_model=list[RoleOut])
async def get_roles(
    tenant_id: UUID,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> list[RoleOut]:
    """List roles in a tenant."""
    _ = admin
    roles = await list_roles(session, tenant_id)
    return [RoleOut.model_validate(r) for r in roles]


@router.get("/roles/{role_id}", response_model=RoleOut)
async def get_role_route(
    role_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> RoleOut:
    """Get a single role."""
    _ = admin
    role = await get_role(session, role_id, tenant_id)
    return RoleOut.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def patch_role(
    role_id: UUID,
    tenant_id: UUID,
    request: UpdateRoleRequest,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> RoleOut:
    """Update role description and/or status."""
    _ = admin
    role = await update_role(session, role_id, tenant_id, request)
    return RoleOut.model_validate(role)


# -----------------------------------------------------------------------------
# Permissions on a role
# -----------------------------------------------------------------------------


@router.post(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionOut,
    status_code=201,
)
async def post_permission(
    role_id: UUID,
    tenant_id: UUID,
    request: SetPermissionRequest,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> RolePermissionOut:
    """Create or update a (role, transaction_type) permission."""
    _ = admin
    perm = await set_permission(session, role_id, tenant_id, request)
    return RolePermissionOut.model_validate(perm)


@router.delete(
    "/roles/{role_id}/permissions/{transaction_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_permission(
    role_id: UUID,
    transaction_type: str,
    tenant_id: UUID,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Remove a (role, transaction_type) permission. Idempotent."""
    _ = admin
    await remove_permission(session, role_id, tenant_id, transaction_type)


@router.get(
    "/roles/{role_id}/permissions",
    response_model=list[RolePermissionOut],
)
async def get_permissions(
    role_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> list[RolePermissionOut]:
    """List all permissions of a role."""
    _ = admin
    perms = await list_permissions(session, role_id, tenant_id)
    return [RolePermissionOut.model_validate(p) for p in perms]


# -----------------------------------------------------------------------------
# User-role assignment
# -----------------------------------------------------------------------------


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleOut,
    status_code=201,
)
async def post_user_role(
    user_id: UUID,
    tenant_id: UUID,
    request: AssignRoleRequest,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> UserRoleOut:
    """Assign a role to a user. Idempotent — re-assigning returns existing row."""
    _ = admin
    row = await assign_role_to_user(session, user_id, tenant_id, request)
    return UserRoleOut.model_validate(row)


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_role(
    user_id: UUID,
    role_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Remove a role from a user. Idempotent."""
    _ = admin
    await remove_role_from_user(session, user_id, tenant_id, role_id)


@router.get("/users/{user_id}/roles", response_model=list[UserRoleOut])
async def get_user_roles(
    user_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = _admin_only,
    session: AsyncSession = Depends(get_async_session),
) -> list[UserRoleOut]:
    """List roles assigned to a user."""
    _ = admin
    rows = await list_user_roles(session, user_id, tenant_id)
    return [UserRoleOut.model_validate(r) for r in rows]


# Bind Body for future expansion (e.g. bulk operations) — currently unused.
_ = Body
