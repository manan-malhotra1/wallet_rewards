"""Reward budgets service — Phase G.1 (WAL-50).

Two surfaces:
  - `check_budget_available()` — read-side guard called inside
    `issue_points_reward` BEFORE any ledger write. Locks the budget row
    `FOR UPDATE` so two concurrent issuances can't both pass the check
    at 99% consumption.
  - Admin CRUD (`create_budget`, `list_budgets_for_tenant`,
    `delete_budget`) — wired by the router.

Consumption is computed live from `reward_events.reward_value`. No
separate counter table — `reward_events` is the source of truth.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin, record_audit_for_system
from app.modules.budgets.schemas import (
    BudgetConsumptionOut,
    BudgetCreateRequest,
    BudgetOut,
)
from app.shared.exceptions import (
    AppHTTPException,
    BudgetExceeded,
    BudgetNotFound,
    TenantNotFound,
)
from app.shared.models import (
    BUDGET_STATUS_ACTIVE,
    BUDGET_WINDOW_CALENDAR_MONTH,
    BUDGET_WINDOW_LIFETIME,
    BUDGET_WINDOW_ROLLING_7D,
    BUDGET_WINDOW_ROLLING_24H,
    RewardBudget,
    RewardEvent,
    Rule,
    Tenant,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


def _window_floor(window_type: str, now: datetime) -> datetime | None:
    """Earliest `created_at` for events that count toward `window_type`.

    Returns None for `lifetime` — no lower bound.
    """
    if window_type == BUDGET_WINDOW_ROLLING_24H:
        return now - timedelta(hours=24)
    if window_type == BUDGET_WINDOW_ROLLING_7D:
        return now - timedelta(days=7)
    if window_type == BUDGET_WINDOW_CALENDAR_MONTH:
        # First day of the current UTC month.
        return now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC
        )
    if window_type == BUDGET_WINDOW_LIFETIME:
        return None
    raise ValueError(f"Unknown window_type {window_type!r}")


async def _sum_consumption(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rule_id: UUID | None,
    currency: str,
    window_floor: datetime | None,
) -> Decimal:
    """Sum reward_events.reward_value matching the budget's scope + window.

    `rule_id is None` → tenant-wide consumption (sum across all rules in
    the tenant + currency). `rule_id` set → only events from that rule.

    `reward_events` has no tenant_id column — we join through `rules`
    (which does), since every reward_event references a rule that lives
    in exactly one tenant.
    """
    stmt = (
        select(func.coalesce(func.sum(RewardEvent.reward_value), 0))
        .join(Rule, Rule.id == RewardEvent.rule_id)
        .where(
            Rule.tenant_id == tenant_id,
            RewardEvent.reward_type == ("cashback" if currency != "PTS" else "points"),
        )
    )
    if rule_id is not None:
        stmt = stmt.where(RewardEvent.rule_id == rule_id)
    if window_floor is not None:
        stmt = stmt.where(RewardEvent.created_at >= window_floor)
    result = await session.execute(stmt)
    raw = result.scalar_one()
    return Decimal(str(raw or 0))


# -----------------------------------------------------------------------------
# Pre-issuance check
# -----------------------------------------------------------------------------


async def check_budget_available(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rule_id: UUID,
    currency: str,
    amount: Decimal,
    now: datetime | None = None,
) -> None:
    """Raise BudgetExceeded if `amount` would breach ANY active budget.

    Evaluates budgets in two passes:
      1. Rule-scoped budgets (most specific, narrowest cap)
      2. Tenant-scoped budgets (catch-all)

    The "narrowest cap" guarantee comes from the unique partial indexes
    on `reward_budgets`: at most one row per scope + currency + window.

    Concurrency: each budget row is locked `FOR UPDATE` so a second
    issuance running in parallel will block on the same row, then see
    the post-write consumption and reject if it would now exceed.

    Side effects on threshold crossings:
      - 50% consumed → audit_log `budget.threshold_50`
      - 80% consumed → audit_log `budget.threshold_80`
      - 100% (this issuance) → audit_log `budget.exhausted`

    Args:
        session: Async DB session (caller commits).
        tenant_id: Tenant scope.
        rule_id: The firing rule — used to check rule-scoped budgets first.
        currency: 'PTS' for points budgets, ISO 4217 for cashback.
        amount: Reward value about to be issued.
        now: Override for tests. Defaults to `datetime.now(UTC)`.

    Raises:
        BudgetExceeded: 409 — current consumption + amount > cap on any
            active budget covering this (tenant, scope, currency, window).
    """
    if amount <= 0:
        return  # No-op — nothing to consume.
    current = now or datetime.now(UTC)

    # 1. Load every active budget that COULD apply to this issuance, locking
    #    rows for the duration of the check. Order matters only for which
    #    audit row gets written first on threshold crossings; the rejection
    #    semantics are the same either way (any breach → reject).
    stmt = (
        select(RewardBudget)
        .where(
            RewardBudget.tenant_id == tenant_id,
            RewardBudget.currency == currency,
            RewardBudget.status == BUDGET_STATUS_ACTIVE,
        )
        .where(
            # Either rule-scoped on THIS rule, or tenant-scoped (scope_id NULL).
            (RewardBudget.scope_id == rule_id) | (RewardBudget.scope_id.is_(None))
        )
        .with_for_update()
    )
    budgets = list((await session.execute(stmt)).scalars().all())

    for budget in budgets:
        floor = _window_floor(budget.window_type, current)
        consumed = await _sum_consumption(
            session,
            tenant_id=tenant_id,
            rule_id=budget.scope_id,
            currency=currency,
            window_floor=floor,
        )
        projected = consumed + amount
        cap = Decimal(str(budget.cap_amount))

        # Threshold audit hooks — write before raising so the trail
        # captures the cause-and-effect even on rejection.
        if cap > 0:
            pct_before = float(consumed / cap) * 100
            pct_after = float(projected / cap) * 100
            for threshold, action in (
                (50, "budget.threshold_50"),
                (80, "budget.threshold_80"),
            ):
                if pct_before < threshold <= pct_after:
                    record_audit_for_system(
                        session,
                        tenant_id=tenant_id,
                        actor_id="system",
                        action=action,
                        entity_type="reward_budget",
                        entity_id=str(budget.id),
                        after_state={
                            "consumed": str(projected),
                            "cap": str(cap),
                            "window_type": budget.window_type,
                        },
                    )

        if projected > cap:
            # Audit the rejection BEFORE raising so the operator sees what
            # blocked it. Caller's transaction will roll back the in-memory
            # state, but we commit this audit row immediately via a
            # nested begin_nested() if available, else accept that on
            # rollback the audit_log row is lost too. Pragmatic: rely on
            # the caller's commit (issue_points_reward catches and writes).
            record_audit_for_system(
                session,
                tenant_id=tenant_id,
                actor_id="system",
                action="budget.exhausted",
                entity_type="reward_budget",
                entity_id=str(budget.id),
                before_state={"consumed": str(consumed), "cap": str(cap)},
                after_state={
                    "would_consume": str(amount),
                    "window_type": budget.window_type,
                },
            )
            raise BudgetExceeded(budget.window_type)


# -----------------------------------------------------------------------------
# Admin CRUD
# -----------------------------------------------------------------------------


async def create_budget(
    session: AsyncSession,
    request: BudgetCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> RewardBudget:
    """Create a new RewardBudget row. Raises 409 on the unique-index
    collision (one budget per scope + currency + window).
    """
    await _assert_tenant_exists(session, request.tenant_id)

    # Validate the scope_id/scope_type pairing — Pydantic's
    # `Literal` doesn't catch this on its own.
    if request.scope_type == "rule" and request.scope_id is None:
        raise AppHTTPException(
            422, "scope_id_required", "scope_id is required when scope_type='rule'."
        )
    if request.scope_type == "tenant" and request.scope_id is not None:
        raise AppHTTPException(
            422,
            "scope_id_not_allowed",
            "scope_id must be omitted when scope_type='tenant'.",
        )

    budget = RewardBudget(
        tenant_id=request.tenant_id,
        scope_type=request.scope_type,
        scope_id=request.scope_id,
        currency=request.currency.upper(),
        window_type=request.window_type,
        cap_amount=request.cap_amount,
        status=request.status,
    )
    session.add(budget)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "budget_already_exists",
            "A budget already exists for this scope + currency + window.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="budget.created",
            entity_type="reward_budget",
            entity_id=str(budget.id),
            after_state={
                "scope_type": budget.scope_type,
                "scope_id": str(budget.scope_id) if budget.scope_id else None,
                "currency": budget.currency,
                "window_type": budget.window_type,
                "cap_amount": str(budget.cap_amount),
                "status": budget.status,
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(budget)
    return budget


async def list_budgets_for_tenant(
    session: AsyncSession, tenant_id: UUID
) -> list[BudgetConsumptionOut]:
    """Return every budget in the tenant plus its live consumption."""
    result = await session.execute(
        select(RewardBudget)
        .where(RewardBudget.tenant_id == tenant_id)
        .order_by(RewardBudget.created_at.desc())
    )
    budgets = list(result.scalars().all())
    now = datetime.now(UTC)
    payload: list[BudgetConsumptionOut] = []
    for budget in budgets:
        floor = _window_floor(budget.window_type, now)
        consumed = await _sum_consumption(
            session,
            tenant_id=tenant_id,
            rule_id=budget.scope_id,
            currency=budget.currency,
            window_floor=floor,
        )
        cap = Decimal(str(budget.cap_amount))
        remaining = max(cap - consumed, Decimal("0"))
        pct = float(consumed / cap * 100) if cap > 0 else 0.0
        payload.append(
            BudgetConsumptionOut(
                budget=BudgetOut.model_validate(budget),
                consumed_amount=consumed,
                remaining_amount=remaining,
                percent_consumed=round(pct, 2),
            )
        )
    return payload


async def delete_budget(
    session: AsyncSession,
    budget_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a budget. Tenant-scoped: cross-tenant deletes return 404."""
    result = await session.execute(
        select(RewardBudget).where(
            RewardBudget.id == budget_id,
            RewardBudget.tenant_id == tenant_id,
        )
    )
    budget = result.scalar_one_or_none()
    if budget is None:
        raise BudgetNotFound()

    before = {
        "scope_type": budget.scope_type,
        "scope_id": str(budget.scope_id) if budget.scope_id else None,
        "currency": budget.currency,
        "window_type": budget.window_type,
        "cap_amount": str(budget.cap_amount),
    }
    await session.delete(budget)

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="budget.deleted",
            entity_type="reward_budget",
            entity_id=str(budget_id),
            before_state=before,
            ip_address=ip_address,
        )

    await session.commit()
