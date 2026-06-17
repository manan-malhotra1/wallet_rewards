"""Rules service — rule CRUD operations for the admin/test surface."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.rules.schemas import RuleCreateRequest, RulePerformanceOut
from app.shared.exceptions import RuleNotFound, TenantNotFound
from app.shared.models import RewardEvent, Rule, Tenant


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


async def list_rule_performance_for_tenant(
    session: AsyncSession, *, tenant_id: UUID
) -> list[RulePerformanceOut]:
    """Aggregate `reward_events` for every rule in the tenant — one query.

    Single SQL round-trip with `LEFT JOIN reward_events ON rule_id` and
    `GROUP BY Rule.id`. Rules that have never fired appear with all-zero
    metrics (LEFT JOIN preserves them; `count(reward_event.id)` returns
    0 because COUNT ignores NULLs). Tenant scoping is enforced via the
    WHERE on `Rule.tenant_id` (NFR-0220).

    Exists to avoid the N+1 the per-rule endpoint creates when the
    campaigns list page is rendered for a tenant with many rules.

    Args:
        session: Async DB session (read-only).
        tenant_id: Caller's tenant scope.

    Returns:
        One `RulePerformanceOut` per rule in the tenant, newest rule
        first. Empty tenants return `[]`.
    """
    stmt = (
        select(
            Rule.id,
            func.count(RewardEvent.id),
            func.count(func.distinct(RewardEvent.user_id)),
            func.coalesce(func.sum(RewardEvent.reward_value), 0),
            func.min(RewardEvent.created_at),
            func.max(RewardEvent.created_at),
        )
        .select_from(Rule)
        .outerjoin(RewardEvent, RewardEvent.rule_id == Rule.id)
        .where(Rule.tenant_id == tenant_id)
        .group_by(Rule.id)
        .order_by(Rule.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        RulePerformanceOut(
            rule_id=rule_id,
            total_fires=int(total_fires or 0),
            unique_users_rewarded=int(unique_users or 0),
            total_reward_value=Decimal(str(total_value or 0)),
            first_fired_at=first_at,
            last_fired_at=last_at,
        )
        for rule_id, total_fires, unique_users, total_value, first_at, last_at in rows
    ]


async def get_rule_performance(
    session: AsyncSession, *, tenant_id: UUID, rule_id: UUID
) -> RulePerformanceOut:
    """Aggregate `reward_events` for a single rule (campaign performance).

    Computes everything in one SQL round-trip:
      - COUNT(*) as total_fires
      - COUNT(DISTINCT user_id) as unique_users_rewarded
      - SUM(reward_value) as total_reward_value
      - MIN/MAX(created_at) as first/last_fired_at

    Tenant scoping: rejects with `RuleNotFound` if the rule belongs to a
    different tenant — never leaks metrics across tenants (NFR-0220).

    Args:
        session: Async DB session (no commit needed; this is a read).
        tenant_id: Caller's tenant scope.
        rule_id: Rule (campaign) to summarise.

    Returns:
        Validated `RulePerformanceOut`. Empty rules return all zeros
        with null first/last_fired_at.

    Raises:
        RuleNotFound: rule_id not present, or belongs to another tenant.
    """
    # Tenant-scoped existence check FIRST — otherwise cross-tenant
    # callers would silently get all-zero metrics for a real rule.
    rule_result = await session.execute(
        select(Rule.id).where(Rule.id == rule_id, Rule.tenant_id == tenant_id)
    )
    if rule_result.scalar_one_or_none() is None:
        raise RuleNotFound()

    stmt = select(
        func.count(RewardEvent.id),
        func.count(func.distinct(RewardEvent.user_id)),
        func.coalesce(func.sum(RewardEvent.reward_value), 0),
        func.min(RewardEvent.created_at),
        func.max(RewardEvent.created_at),
    ).where(RewardEvent.rule_id == rule_id)
    row = (await session.execute(stmt)).one()
    total_fires, unique_users, total_value, first_at, last_at = row

    return RulePerformanceOut(
        rule_id=rule_id,
        total_fires=int(total_fires or 0),
        unique_users_rewarded=int(unique_users or 0),
        total_reward_value=Decimal(str(total_value or 0)),
        first_fired_at=first_at,
        last_fired_at=last_at,
    )
