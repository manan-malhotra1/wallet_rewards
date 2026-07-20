"""Step-up policies FastAPI router (admin-gated) — READ ONLY.

Step-up policy WRITES (create / update / delete) now flow exclusively through
the config-governance maker-checker (`/api/v1/config-requests`, config type
"step_up") — the direct create/delete routes were retired so every threshold
change is dual-controlled like pricing / limit / commission / tax. Only the
tenant list stays here. The hot-path enforcement (`enforce_step_up`) lives in
the service module and is called by P2P + redemption — not exposed as a route.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.step_up.schemas import StepUpPolicyOut
from app.modules.step_up.service import list_policies_for_tenant

router = APIRouter(prefix="/api/v1/step-up", tags=["step-up"])


@router.get("/policies", response_model=list[StepUpPolicyOut])
async def get_policies(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[StepUpPolicyOut]:
    """List every step-up policy in the tenant."""
    _ = admin
    return await list_policies_for_tenant(session, tenant_id)
