"""Rules engine evaluator — Phase C: first_time + milestone.

Given a NormalisedEvent, find every active rule in the tenant that matches
the event's transaction_type, then for each one decide whether to fire and
update the user_rule_progress accordingly.

Idempotency is delegated to the rewards layer via the unique index on
`reward_events(user_id, rule_id, triggering_event_id)` — the evaluator
itself is not idempotent on milestone counter increments. For Phase C we
rely on the event_ingestion_log dedup to prevent re-evaluation of the same
event. Phase D will add per-rule idempotency.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.schemas import NormalisedEvent
from app.shared.models import (
    PROGRESS_STATUS_COMPLETED,
    RULE_TYPE_FIRST_TIME,
    RULE_TYPE_MILESTONE,
    Rule,
    UserRuleProgress,
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
        progress = await _get_or_create_progress(session, event.user_id, rule.id)

        # Skip rules already deactivated for this user (stop-after-N hit).
        if progress.status == PROGRESS_STATUS_COMPLETED:
            continue

        # min_amount filter (value-based condition, Pay-PRD-0618).
        if rule.min_amount is not None and event.amount < Decimal(rule.min_amount):
            continue

        firing = _evaluate(rule, progress, event)
        if firing is not None:
            firings.append(firing)

    return firings


async def _find_candidate_rules(
    session: AsyncSession, event: NormalisedEvent
) -> list[Rule]:
    """Return all active rules in the event's tenant whose transaction_type matches.

    Phase C only handles rules with `transaction_type` set (first_time, milestone).
    Composite rules (no transaction_type) are skipped.
    """
    result = await session.execute(
        select(Rule).where(
            Rule.tenant_id == event.tenant_id,
            Rule.status == "active",
            Rule.transaction_type == event.transaction_type,
            Rule.rule_type.in_((RULE_TYPE_FIRST_TIME, RULE_TYPE_MILESTONE)),
        )
    )
    return list(result.scalars().all())


async def _get_or_create_progress(
    session: AsyncSession, user_id, rule_id
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


def _evaluate(
    rule: Rule, progress: UserRuleProgress, event: NormalisedEvent
) -> RuleFiring | None:
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
