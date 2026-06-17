"""Step-up policies FastAPI router (admin-gated).

CRUD for `step_up_policies`. The hot-path enforcement (`enforce_step_up`)
lives in the service module and is called by P2P + redemption — not
exposed as a route.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.step_up.schemas import (
    StepUpPolicyCreateRequest,
    StepUpPolicyOut,
)
from app.modules.step_up.service import (
    create_policy,
    delete_policy,
    list_policies_for_tenant,
)

router = APIRouter(prefix="/api/v1/step-up", tags=["step-up"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


@router.post("/policies", response_model=StepUpPolicyOut, status_code=201)
async def post_policy(
    request: StepUpPolicyCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> StepUpPolicyOut:
    """Create a new step-up policy. 409 if one already exists for the scope."""
    policy = await create_policy(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return StepUpPolicyOut.model_validate(policy)


@router.get("/policies", response_model=list[StepUpPolicyOut])
async def get_policies(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[StepUpPolicyOut]:
    """List every step-up policy in the tenant."""
    _ = admin
    return await list_policies_for_tenant(session, tenant_id)


@router.delete("/policies/{policy_id}", status_code=204)
async def remove_policy(
    policy_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a policy. 404 if missing or cross-tenant."""
    await delete_policy(
        session,
        policy_id,
        tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
