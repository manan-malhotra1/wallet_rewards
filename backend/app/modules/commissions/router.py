"""Commissions module FastAPI router (Pricing v2 Epic 24 — read-only list).

Config WRITES (create/delete) are NOT exposed here — since Epic 22 they go
exclusively through the maker-checker flow (`/api/v1/config-requests`). Only the
admin-gated LIST is exposed, mirroring the pricing router, so the admin UI can
render the current commission schedule.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.commissions.schemas import CommissionConfigOut
from app.modules.commissions.service import list_commission_configs

router = APIRouter(prefix="/api/v1/commissions", tags=["commissions"])


@router.get("/configs", response_model=list[CommissionConfigOut])
async def get_commission_configs(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[CommissionConfigOut]:
    """List every commission config in a tenant (read-only; writes go via approval)."""
    _ = admin
    configs = await list_commission_configs(session, tenant_id)
    return [CommissionConfigOut.model_validate(c) for c in configs]
