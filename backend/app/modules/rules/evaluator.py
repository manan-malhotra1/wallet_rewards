"""Rules engine evaluator — Phase C + Epic 10 expansion.

Given a NormalisedEvent, find every active rule in the tenant that matches
the event's transaction_type, then for each one decide whether to fire and
update the user_rule_progress accordingly.

Supported rule types:
  - first_time  (Phase C)
  - milestone   (Phase C)
  - value_based (Epic 10)
  - campaign    (Epic 10) — first_time semantics, date-gated
  - streak      (Epic 10) — N consecutive periods (day/week)
  - composite   (Epic 10 / WAL-75) — AND/OR over rule_conditions, each a
                count of qualifying transactions (Pay-PRD-0619)

Referral rules (Epic 10 / WAL-77) are NOT driven from here — they fire via the
explicit entry points in `referral_evaluator.py` (signup + nth_transaction),
because their trigger is a signup / referee-activity event, not a generic
transaction event on the acting user.

Idempotency is delegated to the rewards layer via the unique index on
`reward_events(user_id, rule_id, triggering_event_id)` — the evaluator
itself is not idempotent on counter increments. We rely on
event_ingestion_log dedup to prevent re-evaluation of the same event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.schemas import NormalisedEvent
from app.shared.models import (
    PROGRESS_STATUS_COMPLETED,
    RULE_TYPE_CAMPAIGN,
    RULE_TYPE_COMPOSITE,
    RULE_TYPE_FIRST_TIME,
    RULE_TYPE_MILESTONE,
    RULE_TYPE_STREAK,
    RULE_TYPE_VALUE_BASED,
    TXN_STATUS_COMPLETED,
    Rule,
    RuleCondition,
    Transaction,
    UserRuleProgress,
)

# Rule types this evaluator can fire. Listed once so both the candidate
# query and the dispatcher stay in sync.
SUPPORTED_RULE_TYPES = (
    RULE_TYPE_FIRST_TIME,
    RULE_TYPE_MILESTONE,
    RULE_TYPE_VALUE_BASED,
    RULE_TYPE_CAMPAIGN,
    RULE_TYPE_STREAK,
    RULE_TYPE_COMPOSITE,
)


@dataclass(frozen=True)
class RuleFiring:
    """One rule that fired for a given event.

    The caller (events.service.process_external_event) uses this to drive
    reward issuance.
    """

    rule: Rule
    reward_value: Decimal


async def evaluate_active_rules_for_event(
    session: AsyncSession, event: NormalisedEvent
) -> list[RuleFiring]:
    """Evaluate every applicable active rule for the given event.

    Args:
        session: Async DB session (not committed here — caller handles it).
        event: The NormalisedEvent to evaluate against.

    Returns:
        A list of RuleFiring objects (may be empty). Side effect: updates
        `user_rule_progress` for every rule considered.
    """
    rules = await _find_candidate_rules(session, event)
    firings: list[RuleFiring] = []

    for rule in rules:
        # Segment binding (Epic 10 / WAL-79): if the rule is bound to a
        # segment, only users in that segment are eligible. Lazy-imported
        # to avoid a service-layer import cycle.
        if rule.segment_id is not None:
            from app.modules.segments.service import user_is_in_segment

            if not await user_is_in_segment(
                session, user_id=event.user_id, segment_id=rule.segment_id
            ):
                continue

        progress = await _get_or_create_progress(session, event.user_id, rule.id)

        # Skip rules already deactivated for this user (stop-after-N hit).
        if progress.status == PROGRESS_STATUS_COMPLETED:
            continue

        # min_amount filter (value-based condition, Pay-PRD-0618). Composite
        # rules leave rule.min_amount NULL — their per-condition min_amount is
        # applied inside the counting query — so this filter is a no-op for them.
        if rule.min_amount is not None and event.amount < Decimal(rule.min_amount):
            continue

        # Composite rules need DB access (per-condition counting), so they
        # take the async path; every other type is a pure single-event decision.
        if rule.rule_type == RULE_TYPE_COMPOSITE:
            firing = await _evaluate_composite(session, rule, progress, event)
        else:
            firing = _evaluate(rule, progress, event)
        if firing is not None:
            firings.append(firing)

    return firings


async def _find_candidate_rules(session: AsyncSession, event: NormalisedEvent) -> list[Rule]:
    """Return all active rules in the event's tenant that this event can trigger.

    Two shapes match:
      - Flat rules (first_time / milestone / value_based / campaign / streak)
        carry `Rule.transaction_type` directly; they match when it equals the
        event's transaction_type.
      - Composite rules leave `Rule.transaction_type` NULL and carry their
        transaction_types on `rule_conditions`. A composite rule is a
        candidate when ANY of its conditions matches the event's
        transaction_type (subquery on rule_conditions).
    """
    # rule_ids of composite rules that have a condition matching this event.
    composite_match = select(RuleCondition.rule_id).where(
        RuleCondition.transaction_type == event.transaction_type
    )
    result = await session.execute(
        select(Rule).where(
            Rule.tenant_id == event.tenant_id,
            Rule.status == "active",
            Rule.rule_type.in_(SUPPORTED_RULE_TYPES),
            or_(
                Rule.transaction_type == event.transaction_type,
                and_(
                    Rule.rule_type == RULE_TYPE_COMPOSITE,
                    Rule.id.in_(composite_match),
                ),
            ),
        )
    )
    return list(result.scalars().all())


async def _get_or_create_progress(
    session: AsyncSession, user_id: UUID, rule_id: UUID
) -> UserRuleProgress:
    """Find or insert the UserRuleProgress row for this (user, rule) pair.

    Uses INSERT-then-fetch with the unique constraint as the race guard. On
    collision (concurrent first-time evaluation), reload the existing row.
    """
    result = await session.execute(
        select(UserRuleProgress).where(
            UserRuleProgress.user_id == user_id,
            UserRuleProgress.rule_id == rule_id,
        )
    )
    progress = result.scalar_one_or_none()
    if progress is not None:
        return progress

    progress = UserRuleProgress(user_id=user_id, rule_id=rule_id)
    session.add(progress)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # Another concurrent evaluation created it; reload.
        result = await session.execute(
            select(UserRuleProgress).where(
                UserRuleProgress.user_id == user_id,
                UserRuleProgress.rule_id == rule_id,
            )
        )
        progress = result.scalar_one()
    return progress


def _evaluate(rule: Rule, progress: UserRuleProgress, event: NormalisedEvent) -> RuleFiring | None:
    """Type-specific decision for whether this rule fires on this event.

    Mutates the progress row (current_count, trigger_count, etc.). The caller
    commits.

    Returns:
        A RuleFiring if the rule fires; None otherwise.
    """
    if rule.rule_type == RULE_TYPE_FIRST_TIME:
        return _evaluate_first_time(rule, progress, event)
    if rule.rule_type == RULE_TYPE_MILESTONE:
        return _evaluate_milestone(rule, progress, event)
    if rule.rule_type == RULE_TYPE_VALUE_BASED:
        return _evaluate_value_based(rule, progress, event)
    if rule.rule_type == RULE_TYPE_CAMPAIGN:
        return _evaluate_campaign(rule, progress, event)
    if rule.rule_type == RULE_TYPE_STREAK:
        return _evaluate_streak(rule, progress, event)
    return None


def _evaluate_first_time(
    rule: Rule, progress: UserRuleProgress, event: NormalisedEvent
) -> RuleFiring | None:
    """Pay-PRD-0617: fires exactly once per user — the first matching event."""
    if progress.trigger_count > 0:
        return None

    progress.trigger_count = 1
    progress.last_triggered_at = event.timestamp
    progress.last_qualifying_event_at = event.timestamp
    # First-time rules are one-shot; mark progress completed.
    progress.status = PROGRESS_STATUS_COMPLETED
    return RuleFiring(rule=rule, reward_value=Decimal(rule.reward_value))


def _evaluate_milestone(
    rule: Rule, progress: UserRuleProgress, event: NormalisedEvent
) -> RuleFiring | None:
    """Pay-PRD-0540 + 0570: fire after `count_threshold` qualifying events.

    Counter increments on each qualifying event. When it reaches the
    threshold, fire and reset (if `resets_after_trigger`).
    """
    if rule.count_threshold is None:
        return None  # Malformed rule — already rejected at create time.

    progress.current_count += 1
    progress.last_qualifying_event_at = event.timestamp

    if progress.current_count < rule.count_threshold:
        return None  # Not enough yet.

    # Fire.
    progress.trigger_count += 1
    progress.last_triggered_at = event.timestamp

    if rule.resets_after_trigger:
        progress.current_count = 0
        progress.window_start = None

    # Stop-after-N (Pay-PRD-0580).
    if (
        rule.stop_after_n_triggers is not None
        and progress.trigger_count >= rule.stop_after_n_triggers
    ):
        progress.status = PROGRESS_STATUS_COMPLETED

    return RuleFiring(rule=rule, reward_value=Decimal(rule.reward_value))


# -----------------------------------------------------------------------------
# Epic 10 — value-based, campaign, streak
# -----------------------------------------------------------------------------


def _evaluate_value_based(
    rule: Rule, progress: UserRuleProgress, event: NormalisedEvent
) -> RuleFiring | None:
    """Pay-PRD-0618: fires whenever a single qualifying event meets `min_amount`.

    The `min_amount` filter is already enforced in the caller — by the
    time we reach this branch, the event is at or above the threshold.
    Each qualifying event fires once. Honours `stop_after_n_triggers`
    so an operator can cap rewards (e.g. "first 100 high-value txns
    get a bonus").
    """
    progress.trigger_count += 1
    progress.last_triggered_at = event.timestamp
    progress.last_qualifying_event_at = event.timestamp

    if (
        rule.stop_after_n_triggers is not None
        and progress.trigger_count >= rule.stop_after_n_triggers
    ):
        progress.status = PROGRESS_STATUS_COMPLETED

    return RuleFiring(rule=rule, reward_value=Decimal(rule.reward_value))


def _evaluate_campaign(
    rule: Rule, progress: UserRuleProgress, event: NormalisedEvent
) -> RuleFiring | None:
    """Campaign rule — first_time semantics gated by a date window.

    Fires at most once per user, and only when the event timestamp falls
    within `[campaign_start_date, campaign_end_date]` (inclusive). Outside
    the window the rule is a silent no-op (it still "exists" but doesn't
    fire). The schema validators already ensured both dates are present
    for this rule type.
    """
    if rule.campaign_start_date is None or rule.campaign_end_date is None:
        return None  # Malformed; defence-in-depth — schema check covers it.

    event_date = event.timestamp.date()
    if event_date < rule.campaign_start_date or event_date > rule.campaign_end_date:
        return None

    if progress.trigger_count > 0:
        return None

    progress.trigger_count = 1
    progress.last_triggered_at = event.timestamp
    progress.last_qualifying_event_at = event.timestamp
    # Campaign rules are one-shot per user (within window).
    progress.status = PROGRESS_STATUS_COMPLETED
    return RuleFiring(rule=rule, reward_value=Decimal(rule.reward_value))


def _streak_period_index(ts: datetime, unit: str) -> int:
    """Return an integer "period index" for the given timestamp.

    Two events in the same period have the same index; two events one
    period apart differ by exactly 1. Day periods are UTC calendar
    days; week periods are ISO weeks since the epoch. Both are stable
    across daylight-savings shifts because the math is integer-only.
    """
    if unit == "day":
        return ts.toordinal()
    if unit == "week":
        return ts.toordinal() // 7
    raise ValueError(f"Unsupported streak_unit_window: {unit!r}")


def _evaluate_streak(
    rule: Rule, progress: UserRuleProgress, event: NormalisedEvent
) -> RuleFiring | None:
    """Streak rule — N consecutive periods of qualifying events.

    Logic:
      - First qualifying event of a streak → current_streak = 1.
      - Event in the SAME period as the previous → no change (one event
        per period counts; spamming doesn't accelerate the streak).
      - Event in the IMMEDIATE NEXT period → increment current_streak.
      - Event with a GAP > 1 period → streak broken, restart at 1.
      - When current_streak reaches `streak_units` → fire. Reset to 0 if
        `resets_after_trigger`, else freeze at the threshold.

    Honours `stop_after_n_triggers` like milestones do.
    """
    if rule.streak_units is None or rule.streak_unit_window is None:
        return None  # Malformed; defence-in-depth.

    current_idx = _streak_period_index(event.timestamp, rule.streak_unit_window)
    prev_at = progress.last_qualifying_event_at
    if prev_at is None:
        progress.current_streak = 1
    else:
        prev_idx = _streak_period_index(prev_at, rule.streak_unit_window)
        gap = current_idx - prev_idx
        if gap == 0:
            # Same period — don't double-count, just touch the timestamp.
            progress.last_qualifying_event_at = event.timestamp
            return None
        if gap == 1:
            progress.current_streak += 1
        else:
            # Gap > 1 means the streak broke. Restart.
            progress.current_streak = 1

    progress.last_qualifying_event_at = event.timestamp

    if progress.current_streak < rule.streak_units:
        return None

    # Fire.
    progress.trigger_count += 1
    progress.last_triggered_at = event.timestamp
    if rule.resets_after_trigger:
        progress.current_streak = 0

    if (
        rule.stop_after_n_triggers is not None
        and progress.trigger_count >= rule.stop_after_n_triggers
    ):
        progress.status = PROGRESS_STATUS_COMPLETED

    return RuleFiring(rule=rule, reward_value=Decimal(rule.reward_value))


# -----------------------------------------------------------------------------
# Epic 10 / WAL-75 — composite (AND/OR over rule_conditions)
# -----------------------------------------------------------------------------


async def _count_qualifying_transactions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    condition: RuleCondition,
    window_start: datetime | None,
) -> int:
    """Count the user's COMPLETED transactions that satisfy one sub-condition.

    A transaction qualifies when it is COMPLETED, belongs to this user +
    tenant, matches `condition.transaction_type`, meets `condition.min_amount`
    (when set), and — when `window_start` is set — was created at or after it.
    The `transactions` table is the durable, source-agnostic record of a
    user's activity, so counting from it keeps composite rules consistent
    however the driving event arrived.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope (NFR-0220).
        user_id: The acting user.
        condition: The sub-condition whose transaction_type / min_amount gate
            the count.
        window_start: Lower bound on `created_at` for the current counting
            window; None means count over the user's lifetime.

    Returns:
        The number of qualifying transactions.
    """
    stmt = select(func.count(Transaction.id)).where(
        Transaction.tenant_id == tenant_id,
        Transaction.initiated_by == user_id,
        Transaction.transaction_type == condition.transaction_type,
        Transaction.status == TXN_STATUS_COMPLETED,
    )
    if condition.min_amount is not None:
        stmt = stmt.where(Transaction.amount >= condition.min_amount)
    if window_start is not None:
        stmt = stmt.where(Transaction.created_at >= window_start)
    return int((await session.execute(stmt)).scalar_one())


async def _evaluate_composite(
    session: AsyncSession,
    rule: Rule,
    progress: UserRuleProgress,
    event: NormalisedEvent,
) -> RuleFiring | None:
    """Composite rule — combine sub-conditions with AND/OR (Pay-PRD-0619).

    Each sub-condition is "satisfied" when the user's count of qualifying
    transactions of its transaction_type (>= its min_amount when set) reaches
    its count_threshold, counted within the current window (`window_start`).
    AND fires when EVERY condition is satisfied; OR when ANY is.

    Window / reset semantics: a fresh progress row counts over the user's
    lifetime (`window_start` NULL). When the rule fires and
    `resets_after_trigger` is True, `window_start` advances to the triggering
    event's timestamp — the per-condition counting window restarts, so only
    later transactions count toward the next fire. When `resets_after_trigger`
    is False the rule is one-shot: it fires once and does not re-fire (guarded
    below), matching "don't reset, don't repeat".

    Idempotency: replays of the same event never reach here (the ingestion log
    dedupes first), and `issue_points_reward` is guarded by the unique index
    on `reward_events(user_id, rule_id, triggering_event_id)` regardless.

    Returns:
        A RuleFiring when the operator condition is met; None otherwise.

    Side effects:
        Mutates `progress` (trigger_count, timestamps, window_start, status)
        on fire. The caller commits.
    """
    # One-shot guard: a non-resetting composite that has already fired must
    # not re-fire on every subsequent matching event (its window never moves,
    # so its counts would stay above threshold forever).
    if not rule.resets_after_trigger and progress.trigger_count > 0:
        return None

    conditions = list(
        (await session.execute(select(RuleCondition).where(RuleCondition.rule_id == rule.id)))
        .scalars()
        .all()
    )
    # Defence-in-depth: schema validation guarantees >= 2 conditions and a
    # valid operator at create time.
    if len(conditions) < 2 or rule.composite_operator not in ("AND", "OR"):
        return None

    satisfied_flags = [
        await _count_qualifying_transactions(
            session,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            condition=cond,
            window_start=progress.window_start,
        )
        >= cond.count_threshold
        for cond in conditions
    ]

    operator_met = (
        all(satisfied_flags) if rule.composite_operator == "AND" else any(satisfied_flags)
    )
    if not operator_met:
        return None

    # Fire.
    progress.trigger_count += 1
    progress.last_triggered_at = event.timestamp
    progress.last_qualifying_event_at = event.timestamp
    if rule.resets_after_trigger:
        progress.window_start = event.timestamp

    if (
        rule.stop_after_n_triggers is not None
        and progress.trigger_count >= rule.stop_after_n_triggers
    ):
        progress.status = PROGRESS_STATUS_COMPLETED

    return RuleFiring(rule=rule, reward_value=Decimal(rule.reward_value))
