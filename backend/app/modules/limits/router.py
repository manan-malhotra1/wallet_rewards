"""Limits module FastAPI router (Phase G.2, admin-gated).

Config WRITES (create/delete) are NOT exposed here — since Pricing v2 Epic 22
they go exclusively through the maker-checker flow (`/api/v1/config-requests`),
so there is no direct, single-actor path to a live limit / wallet-limit config.
Only the config LIST endpoints remain.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.limits.schemas import LimitConfigOut, WalletLimitConfigOut
from app.modules.limits.service import list_limit_configs, list_wallet_limit_configs

router = APIRouter(prefix="/api/v1/limits", tags=["limits"])


@router.get("/configs", response_model=list[LimitConfigOut])
async def get_limit_configs(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[LimitConfigOut]:
    """List every limit config in a tenant (read-only; writes go via approval)."""
    _ = admin
    configs = await list_limit_configs(session, tenant_id)
    return [LimitConfigOut.model_validate(c) for c in configs]


@router.get("/wallet-configs", response_model=list[WalletLimitConfigOut])
async def get_wallet_limit_configs(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[WalletLimitConfigOut]:
    """List every wallet limit config in a tenant (read-only; writes go via approval)."""
    _ = admin
    configs = await list_wallet_limit_configs(session, tenant_id)
    return [WalletLimitConfigOut.model_validate(c) for c in configs]
