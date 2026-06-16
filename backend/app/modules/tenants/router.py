"""Tenants module FastAPI router (Phase F.5 — admin-gated).

Read-only endpoint for the admin UI's tenant switcher. Lists every tenant
the platform knows about; the UI further filters by which tenants the
authenticated operator has access to (driven by Keycloak attributes when
that wiring lands; for now every admin sees all tenants).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.tenants.schemas import TenantOut
from app.shared.models import Tenant

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[TenantOut]:
    """Return every active tenant, newest first.

    Any authenticated admin can read this list — Phase G will scope it via
    per-admin tenant-access attributes when those land.
    """
    _ = admin
    result = await session.execute(
        select(Tenant).order_by(Tenant.created_at.desc())
    )
    return [TenantOut.model_validate(t) for t in result.scalars().all()]
