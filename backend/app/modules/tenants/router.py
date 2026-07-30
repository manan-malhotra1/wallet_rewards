"""Tenants module FastAPI router (Phase 1 — admin-gated identity card).

Phase 1 endpoints:
  GET    /api/v1/tenants                   — list (existing, Phase F.5)
  POST   /api/v1/tenants                   — create + provision (platform-admin)
  GET    /api/v1/tenants/{id}              — single tenant (admin identity card)
  PATCH  /api/v1/tenants/{id}              — edit name / business_type
  GET    /api/v1/tenants/{id}/branding     — read cosmetic branding (platform-admin)
  PUT    /api/v1/tenants/{id}/branding     — set cosmetic branding (platform-admin)

The UI's tenant switcher uses LIST; the new tenants admin page uses GET
and PATCH for the per-tenant identity card, and GET/PUT branding for the
per-tenant theme. Branding is a direct edit (cosmetic, not maker-checker).
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin, require_admin_role
from app.modules.tenants.schemas import (
    TenantBrandingOut,
    TenantBrandingUpdate,
    TenantCreate,
    TenantOut,
    TenantUpdateRequest,
)
from app.modules.tenants.service import (
    create_tenant,
    get_tenant_branding,
    get_tenant_by_id,
    update_tenant,
    update_tenant_branding,
)
from app.shared.models import Tenant

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[TenantOut]:
    """Return every active tenant, newest first.

    Any authenticated admin can read this list — per-admin tenant-access
    attributes (read from Keycloak) will scope it in Phase 5 alongside
    partner identity.
    """
    _ = admin
    result = await session.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return [TenantOut.model_validate(t) for t in result.scalars().all()]


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def post_tenant(
    payload: TenantCreate,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> TenantOut:
    """Create a tenant and provision its baseline instruments + services.

    Platform-admin only. The new tenant is never left un-provisioned: its
    fiat wallet instrument is keyed to its own `base_currency` and the full
    baseline service set is created in the same transaction.
    """
    _ = admin
    tenant = await create_tenant(session, payload)
    return TenantOut.model_validate(tenant)


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: uuid.UUID,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> TenantOut:
    """Return one tenant for the admin identity card."""
    _ = admin
    tenant = await get_tenant_by_id(tenant_id, session)
    return TenantOut.model_validate(tenant)


@router.patch("/{tenant_id}", response_model=TenantOut)
async def patch_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> TenantOut:
    """Update an existing tenant's name / business_type."""
    tenant = await update_tenant(
        tenant_id,
        payload,
        session,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return TenantOut.model_validate(tenant)


@router.get("/{tenant_id}/branding", response_model=TenantBrandingOut)
async def get_branding(
    tenant_id: uuid.UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> TenantBrandingOut:
    """Return a tenant's branding for the admin UI theme (platform-admin only)."""
    _ = admin
    tenant = await get_tenant_branding(tenant_id, session)
    return TenantBrandingOut.model_validate(tenant)


@router.put("/{tenant_id}/branding", response_model=TenantBrandingOut)
async def put_branding(
    tenant_id: uuid.UUID,
    payload: TenantBrandingUpdate,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> TenantBrandingOut:
    """Set a tenant's branding directly (cosmetic — not maker-checker)."""
    _ = admin
    tenant = await update_tenant_branding(tenant_id, payload, session)
    return TenantBrandingOut.model_validate(tenant)
