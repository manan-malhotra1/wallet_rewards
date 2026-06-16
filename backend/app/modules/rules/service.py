"""Rules service — rule CRUD operations for the admin/test surface."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.rules.schemas import RuleCreateRequest
from app.shared.exceptions import TenantNotFound
from app.shared.models import Rule, Tenant


async def _assert_tenant_exists(session: AsyncSession, tenant_id) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def create_rule(
    session: AsyncSession,
    request: RuleCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> Rule:
    """Persist a new Rule row.

    Pydantic validation has already enforced cross-field consistency (e.g.
    milestone requires count_threshold). Here we only check tenant existence.

    Args:
        session: Async DB session.
        request: Validated RuleCreateRequest.
        admin: Authenticated admin (audit context). Optional for internal callers.
        ip_address: Caller IP (audit context).

    Returns:
        The persisted Rule.

    Raises:
        TenantNotFound: 404 when tenant_id is unknown.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    rule = Rule(
        tenant_id=request.tenant_id,
        name=request.name,
        description=request.description,
        rule_type=request.rule_type,
        transaction_type=request.transaction_type,
        count_threshold=request.count_threshold,
        min_amount=request.min_amount,
        time_window=request.time_window,
        reward_type=request.reward_type,
        reward_value=request.reward_value,
        stop_after_n_triggers=request.stop_after_n_triggers,
        resets_after_trigger=request.resets_after_trigger,
    )
    session.add(rule)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="rule.created",
            entity_type="rule",
            entity_id=str(rule.id),
            after_state={
                "name": rule.name,
                "rule_type": rule.rule_type,
                "transaction_type": rule.transaction_type,
                "reward_type": rule.reward_type,
                "reward_value": str(rule.reward_value),
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(rule)
    return rule


async def list_rules_for_tenant(
    session: AsyncSession, tenant_id
) -> list[Rule]:
    """Return every Rule in the tenant — newest first."""
    result = await session.execute(
        select(Rule)
        .where(Rule.tenant_id == tenant_id)
        .order_by(Rule.created_at.desc())
    )
    return list(result.scalars().all())
