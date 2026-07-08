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
    RuleUpdateRequest,
)
from app.modules.rules.service import (
    create_rule,
    get_rule_by_id,
    get_rule_performance,
    list_rule_performance_for_tenant,
    list_rules_for_tenant,
    soft_delete_rule,
    update_rule,
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


@router.get("/performance", response_model=list[RulePerformanceOut])
async def get_performance_batch(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[RulePerformanceOut]:
    """Batch campaign performance for every rule in the tenant.

    One SQL round-trip; rules with zero fires appear with zero metrics
    (LEFT JOIN). Backs the campaigns list page — kept distinct from the
    per-rule endpoint, which the campaign-detail drawer will still use.
    Admin-only.
    """
    _ = admin
    return await list_rule_performance_for_tenant(session, tenant_id=tenant_id)


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
    return await get_rule_performance(session, tenant_id=tenant_id, rule_id=rule_id)


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(
    rule_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RuleOut:
    """Fetch a single rule. Tenant-scoped — 404 cross-tenant."""
    _ = admin
    rule = await get_rule_by_id(session, tenant_id=tenant_id, rule_id=rule_id)
    return RuleOut.model_validate(rule)


@router.patch("/{rule_id}", response_model=RuleOut)
async def patch_rule(
    rule_id: UUID,
    tenant_id: UUID,
    request: RuleUpdateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RuleOut:
    """Patch a rule's editable fields (name, description, reward, status).

    Trigger conditions (count_threshold, min_amount, etc.) are intentionally
    not editable. Tenant-scoped — 404 cross-tenant.
    """
    rule = await update_rule(
        session,
        tenant_id=tenant_id,
        rule_id=rule_id,
        request=request,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return RuleOut.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def remove_rule(
    rule_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Soft-delete a rule (status='inactive') so it stops firing.

    Hard-delete is rejected by the FK on `reward_events.rule_id` once
    the rule has fired — those rows are auditable history. Operators
    wanting a true purge should drop them at the DB level.
    """
    await soft_delete_rule(
        session,
        tenant_id=tenant_id,
        rule_id=rule_id,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
