"""Batch evaluator for dynamic segments (spec §4).

Per tenant: collect every dynamic (`criteria IS NOT NULL`) segment, compute
each distinct (metric, txn_type, window_days) referenced across all of them
exactly once, evaluate every segment's criteria per candidate user, resolve
exclusivity within each `group_id` (highest `priority` wins, oldest
`created_at` then `id` breaks ties), then diff the result against
`user_segments WHERE source='criteria'`. Manually-assigned rows
(`source='manual'`) are never inserted, updated, or deleted here — see
`_apply_segment_delta`'s unique-constraint guard. The caller owns the
transaction: this module flushes but never commits.

Spec: docs/superpowers/specs/2026-08-12-ai-segmentation-design.md §4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import record_audit_for_system
from app.modules.segments.criteria import Condition, SegmentCriteria
from app.modules.segments.metrics import compute_metric
from app.shared.models import (
    USER_SEGMENT_SOURCE_CRITERIA,
    USER_SEGMENT_SOURCE_MANUAL,
    Segment,
    User,
    UserSegment,
)

# One entry per distinct metric computation the evaluator needs to run:
# (metric name, optional txn_type filter, optional rolling window in days).
# Two conditions that share a key (even across different segments) reuse the
# same computed value map instead of recomputing it.
MetricKey = tuple[str, str | None, int | None]


def _condition_key(cond: Condition) -> MetricKey:
    """Build the metric-computation key a condition reads its value from.

    Args:
        cond: One parsed criteria condition.

    Returns:
        The (metric, txn_type, window_days) tuple identifying which computed
        value map this condition should be evaluated against.
    """
    return (cond.metric, cond.txn_type, cond.window_days)


def _condition_met(cond: Condition, value: Decimal) -> bool:
    """Evaluate a single condition's comparator(s) against one Decimal value.

    Args:
        cond: The condition. `eq` is exclusive of `gte`/`lte` (validated by
            `Condition._check_shape`); `gte`/`lte` may combine (closed range).
        value: The candidate user's value for this condition's metric key.

    Returns:
        True if `value` satisfies every comparator present on `cond`.

    Note:
        Thresholds convert via `Decimal(str(cond.gte))` etc — never compare a
        raw float to a Decimal (see `criteria.Condition`'s docstring:
        `Decimal(0.1) != Decimal("0.1")` due to binary float representation).
    """
    if cond.eq is not None:
        return value == Decimal(str(cond.eq))
    matched = True
    if cond.gte is not None:
        matched = matched and value >= Decimal(str(cond.gte))
    if cond.lte is not None:
        matched = matched and value <= Decimal(str(cond.lte))
    return matched


def _matches(
    criteria: SegmentCriteria,
    values_by_key: dict[MetricKey, dict[UUID, Decimal]],
    user_id: UUID,
) -> bool:
    """Evaluate a full criteria document for one user.

    Args:
        criteria: Parsed `SegmentCriteria` (one AND/OR level over 1-10 flat
            conditions — no nesting in v1).
        values_by_key: Every distinct metric key's precomputed
            {user_id: Decimal} map for this recompute run.
        user_id: The user being evaluated. A user absent from a metric's
            value map defaults to `Decimal(0)` — correct because every
            builder except `days_since_last_txn` omits zero-contribution
            users, and that one already fills in every tenant user (see
            `metrics.py`'s "Shared builder contract").

    Returns:
        True if the user matches: all conditions for `op == "AND"`, any
        condition for `op == "OR"`.
    """
    outcomes = (
        _condition_met(cond, values_by_key[_condition_key(cond)].get(user_id, Decimal(0)))
        for cond in criteria.conditions
    )
    return all(outcomes) if criteria.op == "AND" else any(outcomes)


def _matches_absent_profile(criteria: SegmentCriteria) -> bool:
    """Would this criteria match a hypothetical user with zero on every metric?

    A user who has never touched any metered activity contributes zero to
    every builder's value map and is therefore invisible to the "union of
    computed value-map keys" universe below — UNLESS the criteria would
    itself select such a user (an `lte`-only condition, `eq: 0`, `gte: 0`,
    etc). This check decides whether the candidate universe must be widened
    to every tenant user to avoid silently missing those matches.
    `days_since_last_txn` already fills in every tenant user via its
    sentinel (see `metrics.NEVER_TRANSACTED_DAYS`), so this only changes the
    outcome for *other* metrics' lte/eq-zero conditions.

    Args:
        criteria: Parsed `SegmentCriteria` to test against an all-zero profile.

    Returns:
        True if every metric read as `Decimal(0)` still satisfies the criteria.
    """
    outcomes = (_condition_met(cond, Decimal(0)) for cond in criteria.conditions)
    return all(outcomes) if criteria.op == "AND" else any(outcomes)


async def _compute_all_metric_keys(
    session: AsyncSession,
    tenant_id: UUID,
    keys: set[MetricKey],
    now: datetime,
) -> dict[MetricKey, dict[UUID, Decimal]]:
    """Compute each distinct (metric, txn_type, window_days) key exactly once.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope every computation to (NFR-0220).
        keys: Distinct metric keys referenced by the criteria being evaluated.
        now: The single evaluation instant threaded into every
            `compute_metric` call so the whole run is internally consistent.

    Returns:
        Mapping of metric key to its {user_id: Decimal} value map.
    """
    return {
        (metric, txn_type, window_days): await compute_metric(
            session, tenant_id, metric, txn_type=txn_type, window_days=window_days, now=now
        )
        for metric, txn_type, window_days in keys
    }


async def _candidate_universe(
    session: AsyncSession,
    tenant_id: UUID,
    criteria_list: list[SegmentCriteria],
    values_by_key: dict[MetricKey, dict[UUID, Decimal]],
) -> set[UUID]:
    """Build the set of users to evaluate every criteria document against.

    Starts as the union of every computed value-map key (every user who
    contributed nonzero to at least one referenced metric). If any criteria
    in `criteria_list` would match an all-zero profile (see
    `_matches_absent_profile`), the universe is widened to every user of the
    tenant with one extra query — otherwise a genuinely inactive user (who
    appears in no value map) would never be considered for an
    `lte`/`eq`-zero-style match.

    Args:
        session: Async DB session.
        tenant_id: Tenant being evaluated.
        criteria_list: Every criteria document being evaluated this run.
        values_by_key: Precomputed metric value maps (see
            `_compute_all_metric_keys`).

    Returns:
        The full candidate user_id set.
    """
    universe: set[UUID] = set()
    for value_map in values_by_key.values():
        universe |= value_map.keys()

    if any(_matches_absent_profile(criteria) for criteria in criteria_list):
        result = await session.execute(select(User.id).where(User.tenant_id == tenant_id))
        universe |= {row[0] for row in result.all()}
    return universe


def _resolve_group_winners(
    segments: list[Segment],
    parsed: dict[UUID, SegmentCriteria],
    values_by_key: dict[MetricKey, dict[UUID, Decimal]],
    universe: set[UUID],
) -> dict[UUID, set[UUID]]:
    """Resolve, per user, the single winning segment in each exclusive group.

    Segments are walked in `(-priority, created_at, id)` order (highest
    priority first; ties broken by oldest `created_at`, then `id`, for
    determinism). For each user, the first matching segment in that order
    wins its group; the user is then skipped for every other segment sharing
    that `group_id` (exclusive within a group) but is still evaluated against
    every OTHER group (a user can win in many groups).

    Args:
        segments: Every dynamic segment for this tenant.
        parsed: segment_id -> its parsed `SegmentCriteria`.
        values_by_key: Precomputed metric value maps.
        universe: Candidate user ids to evaluate (see `_candidate_universe`).

    Returns:
        Mapping of segment_id -> the set of user ids that segment won for.
    """
    ordered = sorted(segments, key=lambda seg: (-seg.priority, seg.created_at, seg.id))
    winners: dict[UUID, set[UUID]] = {seg.id: set() for seg in segments}

    for user_id in universe:
        won_groups: set[UUID] = set()
        for seg in ordered:
            if seg.group_id in won_groups:
                continue
            if _matches(parsed[seg.id], values_by_key, user_id):
                winners[seg.id].add(user_id)
                won_groups.add(seg.group_id)

    return winners


async def _apply_segment_delta(
    session: AsyncSession, segment: Segment, desired: set[UUID]
) -> dict[str, int]:
    """Diff one segment's desired criteria membership against its current rows.

    Loads the segment's existing membership split by `source` so manually
    assigned rows are never touched: `uq_user_segments_pair` spans
    (user_id, segment_id) regardless of source, so a manual member who now
    also matches by criteria MUST be excluded from `to_add` — inserting a
    second row for the same pair would violate that constraint.

    Args:
        session: Async DB session.
        segment: The segment being recomputed.
        desired: User ids whose criteria currently match this segment.

    Returns:
        {"added": N, "removed": M, "member_count": len(desired)} — member_count
        is the criteria-desired count; manual-only members are not included.

    Side effects:
        Adds new `UserSegment(source='criteria')` rows to the session and
        issues a bulk delete for stale criteria rows. Does not flush/commit.
    """
    rows = await session.execute(
        select(UserSegment.user_id, UserSegment.source).where(UserSegment.segment_id == segment.id)
    )
    current_criteria: set[UUID] = set()
    manual: set[UUID] = set()
    for user_id, source in rows.all():
        if source == USER_SEGMENT_SOURCE_CRITERIA:
            current_criteria.add(user_id)
        elif source == USER_SEGMENT_SOURCE_MANUAL:
            manual.add(user_id)

    to_add = desired - current_criteria - manual
    to_remove = current_criteria - desired

    for user_id in to_add:
        session.add(
            UserSegment(user_id=user_id, segment_id=segment.id, source=USER_SEGMENT_SOURCE_CRITERIA)
        )
    if to_remove:
        await session.execute(
            delete(UserSegment).where(
                UserSegment.segment_id == segment.id,
                UserSegment.source == USER_SEGMENT_SOURCE_CRITERIA,
                UserSegment.user_id.in_(to_remove),
            )
        )

    return {"added": len(to_add), "removed": len(to_remove), "member_count": len(desired)}


async def recompute_tenant(
    session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> dict[UUID, dict[str, Any]]:
    """Recompute every dynamic segment's membership for one tenant.

    Algorithm (spec §4): collect dynamic segments, compute each distinct
    metric key once, evaluate criteria per candidate user, resolve
    highest-priority winner per exclusive group, diff against
    `source='criteria'` rows (manual rows untouched), apply the delta, stamp
    `last_evaluated_at`, and audit-log every segment whose membership changed.

    Args:
        session: Async DB session. The caller owns the transaction/commit.
        tenant_id: Tenant to recompute (NFR-0220 — every query stays scoped).
        now: Evaluation instant threaded through every metric computation.
            Defaults to the current UTC instant, computed ONCE here so the
            whole recompute is internally consistent; pass an explicit value
            for deterministic/reproducible runs (e.g. tests).

    Returns:
        Mapping of segment_id -> {"added": int, "removed": int,
        "member_count": int}. Static (criteria-NULL) segments are absent.

    Side effects:
        Inserts/deletes `user_segments` rows with `source='criteria'`, sets
        `Segment.last_evaluated_at`, writes one `audit_log` row per changed
        segment (action `segment.recomputed`, actor system), and flushes the
        session. Never commits.
    """
    effective_now = now or datetime.now(UTC)

    candidate_segments = (
        (
            await session.execute(
                select(Segment).where(Segment.tenant_id == tenant_id, Segment.criteria.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    # Defense-in-depth: JSONB's `none_as_null` flag defaults to False, so a
    # caller that explicitly assigns `criteria=None` (rather than omitting the
    # field) stores a JSON 'null' literal — which satisfies the SQL
    # `IS NOT NULL` filter above yet deserializes back to Python `None`.
    # Treat those rows as static too instead of crashing on
    # `SegmentCriteria.model_validate(None)`.
    segments = [seg for seg in candidate_segments if seg.criteria is not None]
    if not segments:
        return {}

    parsed: dict[UUID, SegmentCriteria] = {
        seg.id: SegmentCriteria.model_validate(seg.criteria) for seg in segments
    }

    keys: set[MetricKey] = {
        _condition_key(cond) for criteria in parsed.values() for cond in criteria.conditions
    }
    values_by_key = await _compute_all_metric_keys(session, tenant_id, keys, effective_now)
    universe = await _candidate_universe(session, tenant_id, list(parsed.values()), values_by_key)
    winners = _resolve_group_winners(list(segments), parsed, values_by_key, universe)

    summary: dict[UUID, dict[str, Any]] = {}
    for seg in segments:
        result = await _apply_segment_delta(session, seg, winners[seg.id])
        seg.last_evaluated_at = effective_now
        summary[seg.id] = result
        if result["added"] + result["removed"] > 0:
            record_audit_for_system(
                session,
                tenant_id=tenant_id,
                action="segment.recomputed",
                entity_type="segment",
                entity_id=str(seg.id),
                after_state=result,
            )

    await session.flush()
    return summary


async def preview_criteria(
    session: AsyncSession,
    tenant_id: UUID,
    criteria: SegmentCriteria,
    *,
    now: datetime | None = None,
) -> int:
    """Dry-run count of users a criteria document would currently match.

    Used by the manual/AI criteria builder for live preview counts before a
    segment is created or edited. Computes only the metric keys this one
    criteria document references and touches no rows.

    Args:
        session: Async DB session.
        tenant_id: Tenant to evaluate against.
        criteria: The (not-yet-persisted, or being-edited) criteria to preview.
        now: Evaluation instant; defaults to the current UTC instant.

    Returns:
        The count of matching users. Applies the same absent-user universe
        widening as `recompute_tenant` (see `_candidate_universe`), so an
        lte/eq-zero-style preview correctly counts inactive users.
    """
    effective_now = now or datetime.now(UTC)
    keys = {_condition_key(cond) for cond in criteria.conditions}
    values_by_key = await _compute_all_metric_keys(session, tenant_id, keys, effective_now)
    universe = await _candidate_universe(session, tenant_id, [criteria], values_by_key)
    return sum(1 for user_id in universe if _matches(criteria, values_by_key, user_id))
