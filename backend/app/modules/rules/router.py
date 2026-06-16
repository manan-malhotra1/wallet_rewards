"""Rules module FastAPI router (Phase F.4 — admin-gated).

Both endpoints are admin-only: rule creation directly controls reward
issuance, and the listing exposes the tenant's full rule catalogue.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.rules.schemas import (
    RuleCreateRequest,
    RuleOut,
    RulePerformanceOut,
)
from app.modules.rules.service import (
    create_rule,
    get_rule_performance,
    list_rules_for_tenant,
)

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


@router.post("", response_model=RuleOut, status_code=201)
async def post_rule(
    request: RuleCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RuleOut:
    """Create a new rule (Pay-PRD-0530 to 0560).

    Admin-only — rules govern reward issuance. Requires `platform-admin`
    role. Audit row recorded (Phase F.5, NFR-0250).
    """
    rule = await create_rule(
        session,
        request,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return RuleOut.model_validate(rule)


@router.get("", response_model=list[RuleOut])
async def get_rules(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[RuleOut]:
    """List all rules for a tenant (admin-only)."""
    _ = admin
    rules = await list_rules_for_tenant(session, tenant_id)
    return [RuleOut.model_validate(r) for r in rules]


@router.get("/{rule_id}/performance", response_model=RulePerformanceOut)
async def get_performance(
    rule_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RulePerformanceOut:
    """Return campaign performance metrics for a rule.

    Admin-only. Tenant-scoped — cross-tenant lookups return 404 to avoid
    leaking the rule's existence.
    """
    _ = admin
    return await get_rule_performance(
        session, tenant_id=tenant_id, rule_id=rule_id
    )
