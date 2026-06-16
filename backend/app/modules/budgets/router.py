"""Budgets module FastAPI router (Phase G.1, admin-gated)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.budgets.schemas import (
    BudgetConsumptionOut,
    BudgetCreateRequest,
    BudgetOut,
)
from app.modules.budgets.service import (
    create_budget,
    delete_budget,
    list_budgets_for_tenant,
)

router = APIRouter(prefix="/api/v1/budgets", tags=["budgets"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=BudgetOut, status_code=201)
async def post_budget(
    request: BudgetCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> BudgetOut:
    """Create a reward budget. Admin-only. Audit row recorded."""
    budget = await create_budget(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return BudgetOut.model_validate(budget)


@router.get("", response_model=list[BudgetConsumptionOut])
async def get_budgets(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[BudgetConsumptionOut]:
    """List every budget in a tenant with live consumption + percent used."""
    _ = admin
    return await list_budgets_for_tenant(session, tenant_id)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget_route(
    budget_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a budget. Cross-tenant → 404."""
    await delete_budget(
        session,
        budget_id,
        tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
