"""Tenants module FastAPI router (Phase 1 — admin-gated identity card).

Phase 1 endpoints:
  GET    /api/v1/tenants            — list (existing, Phase F.5)
  GET    /api/v1/tenants/{id}       — single tenant (admin identity card)
  PATCH  /api/v1/tenants/{id}       — edit name / business_type

The UI's tenant switcher uses LIST; the new tenants admin page uses GET
and PATCH for the per-tenant identity card.
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.tenants.schemas import TenantOut, TenantUpdateRequest
from app.modules.tenants.service import get_tenant_by_id, update_tenant
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
