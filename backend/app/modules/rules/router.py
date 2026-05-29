"""Rules module FastAPI router (Phase C test-only endpoints)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.modules.rules.schemas import RuleCreateRequest, RuleOut
from app.modules.rules.service import create_rule, list_rules_for_tenant

router = APIRouter(prefix="/api/v1/rules", tags=["rules (test-only)"])


@router.post("", response_model=RuleOut, status_code=201)
async def post_rule(
    request: RuleCreateRequest,
    session: AsyncSession = Depends(get_async_session),
) -> RuleOut:
    """Create a new rule (Pay-PRD-0530 to 0560)."""
    rule = await create_rule(session, request)
    return RuleOut.model_validate(rule)


@router.get("", response_model=list[RuleOut])
async def get_rules(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> list[RuleOut]:
    """List all rules for a tenant."""
    rules = await list_rules_for_tenant(session, tenant_id)
    return [RuleOut.model_validate(r) for r in rules]
