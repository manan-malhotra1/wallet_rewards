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

Concurrency: `recompute_tenant` selects the tenant's dynamic segments
`FOR UPDATE` in canonical `id` order (mirrors `rewards/outbox.py`'s locking
pattern). Concurrent recomputes of the SAME tenant therefore serialize on its
segment rows — a second caller blocks until the first commits or rolls back
— rather than racing to insert/delete the same `user_segments` rows.
Because the lock is held for the whole function, callers must NOT hold this
transaction open across external work (network calls, Celery dispatch,
etc.) — do the recompute, then commit promptly. NOTE: this FOR UPDATE
serialization is NOT exercised by this module's test suite — a single
`AsyncSession`/connection can't produce the two independent, concurrently
open transactions needed to prove the second caller actually blocks; that
would require a dedicated two-connection concurrency test.

Spec: docs/superpowers/specs/2026-08-12-ai-segmentation-design.md §4.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import structlog
from pydantic import ValidationError
from sqlalchemy import delete, insert, select
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

log = structlog.get_logger()

# One entry per distinct metric computation the evaluator needs to run:
# (metric name, optional txn_type filter, optional rolling window in days).
# Two conditions that share a key (even across different segments) reuse the
# same computed value map instead of recomputing it.
MetricKey = tuple[str, str | None, int | None]


@dataclass(frozen=True, slots=True)
class _CompiledCondition:
    """One condition pre-resolved against its metric's value map + thresholds.

    Built exactly once per condition per recompute/preview run (never once
    per user): converts `gte`/`lte`/`eq` to `Decimal` via `Decimal(str(...))`
    a single time (never float-to-Decimal directly — see `criteria.py`) and
    holds a direct reference to the metric's precomputed {user_id: Decimal}
    map. The per-user hot loop in `_matches` then does zero Decimal
    reconstruction and zero re-lookup of which map a condition belongs to —
    measured 6.3x faster on the inner comparison than reconstructing
    thresholds per user.
    """

    values: dict[UUID, Decimal]
    gte: Decimal | None
    lte: Decimal | None
    eq: Decimal | None


def _key_for_condition(cond: Condition) -> MetricKey:
    """Build the metric-computation key a condition reads its value from.

    Args:
        cond: One parsed criteria condition.

    Returns:
        The (metric, txn_type, window_days) tuple identifying which computed
        value map this condition should be evaluated against.
    """
    return (cond.metric, cond.txn_type, cond.window_days)


def _compile_condition(
    cond: Condition, values_by_key: dict[MetricKey, dict[UUID, Decimal]]
) -> _CompiledCondition:
    """Resolve one condition's value map + Decimal thresholds exactly once.

    Args:
        cond: The condition to compile.
        values_by_key: Every distinct metric key's precomputed value map for
            this run (see `_compute_all_metric_keys`).

    Returns:
        A `_CompiledCondition` ready for repeated per-user evaluation.
    """
    return _CompiledCondition(
        values=values_by_key[_key_for_condition(cond)],
        gte=Decimal(str(cond.gte)) if cond.gte is not None else None,
        lte=Decimal(str(cond.lte)) if cond.lte is not None else None,
        eq=Decimal(str(cond.eq)) if cond.eq is not None else None,
    )


def _compiled_condition_met(compiled: _CompiledCondition, user_id: UUID) -> bool:
    """Evaluate one precompiled condition for a user — no Decimal work here.

    Args:
        compiled: A `_CompiledCondition` built by `_compile_condition`.
        user_id: The candidate user. Absent from `compiled.values` defaults
            to `Decimal(0)` — correct because every metric builder except
            `days_since_last_txn` omits zero-contribution users, and that one
            already fills in every tenant user (see `metrics.py`'s "Shared
            builder contract").

    Returns:
        True if the user's value satisfies every comparator on `compiled`.
    """
    value = compiled.values.get(user_id, Decimal(0))
    if compiled.eq is not None:
        return value == compiled.eq
    matched = True
    if compiled.gte is not None:
        matched = matched and value >= compiled.gte
    if compiled.lte is not None:
        matched = matched and value <= compiled.lte
    return matched


def _matches(op: str, compiled_conditions: list[_CompiledCondition], user_id: UUID) -> bool:
    """Evaluate a compiled criteria document for one user.

    Args:
        op: `"AND"` or `"OR"` (`SegmentCriteria.op`).
        compiled_conditions: The document's conditions, precompiled by
            `_compile_condition`.
        user_id: The user being evaluated.

    Returns:
        True if the user matches: all conditions for `op == "AND"`, any
        condition for `op == "OR"`.
    """
    outcomes = (_compiled_condition_met(c, user_id) for c in compiled_conditions)
    return all(outcomes) if op == "AND" else any(outcomes)


def _matches_absent_profile(op: str, compiled_conditions: list[_CompiledCondition]) -> bool:
    """Would this criteria match a hypothetical user with zero on every metric?

    A user who has never touched any metered activity contributes zero to
    every builder's value map and is therefore invisible to the "union of
    computed value-map keys" universe — UNLESS the criteria would itself
    select such a user (an `lte`-only condition, `eq: 0`, `gte: 0`, etc).
    This decides whether the candidate universe must be widened to every
    tenant user to avoid silently missing those matches. `days_since_last_txn`
    already fills in every tenant user via its sentinel (see
    `metrics.NEVER_TRANSACTED_DAYS`), so this only changes the outcome for
    *other* metrics' lte/eq-zero conditions.

    Implemented by evaluating the ALREADY-COMPILED conditions against a
    freshly generated probe UUID: since no real user can ever occupy a
    freshly minted `uuid4()` (collision probability is astronomically zero),
    `compiled.values.get(probe, Decimal(0))` always yields the all-zero
    profile — reusing `_matches` instead of duplicating comparator logic.

    Args:
        op: `"AND"` or `"OR"`.
        compiled_conditions: The document's precompiled conditions.

    Returns:
        True if a hypothetical zero-everything user would match.
    """
    return _matches(op, compiled_conditions, uuid4())


async def _compute_all_metric_keys(
    session: AsyncSession,
    tenant_id: UUID,
    keys: set[MetricKey],
    now: datetime,
) -> dict[MetricKey, dict[UUID, Decimal]]:
    """Compute each distinct (metric, txn_type, window_days) key exactly once.

    Memory ceiling: each computed map holds one (UUID, Decimal) pair per
    contributing user — roughly ~220 bytes/entry in CPython, so a single
    100k-user map is ~22MB. The working set here is bounded by the number of
    DISTINCT keys across every segment's conditions (deduplicated, not
    segments x conditions) — but a tenant with many segments each using a
    unique metric/window combination approaches that product. Flag for
    Task 5's Celery worker memory budget if a tenant's distinct-key count
    grows large.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope every computation to (NFR-0220).
        keys: Distinct metric keys referenced by the criteria being evaluated.
        now: The single evaluation instant threaded into every
            `compute_metric` call so the whole run is internally consistent.

    Returns:
        Mapping of metric key to its {user_id: Decimal} value map.
    """
    # Sequential awaits are deliberate: one AsyncSession cannot run concurrent
    # queries on its single underlying connection — asyncio.gather here would
    # raise "another operation in progress", not parallelise anything.
    return {
        (metric, txn_type, window_days): await compute_metric(
            session, tenant_id, metric, txn_type=txn_type, window_days=window_days, now=now
        )
        for metric, txn_type, window_days in keys
    }


async def _load_candidate_universe(
    session: AsyncSession,
    tenant_id: UUID,
    criteria_and_conditions: Iterable[tuple[str, list[_CompiledCondition]]],
) -> set[UUID]:
    """Build the set of users to evaluate every criteria document against.

    Starts as the union of every compiled condition's value-map keys (every
    user who contributed nonzero to at least one referenced metric). If any
    (op, compiled_conditions) pair would match an all-zero profile (see
    `_matches_absent_profile`), the universe is widened to every user of the
    tenant with one extra query — otherwise a genuinely inactive user (who
    appears in no value map) would never be considered for an
    `lte`/`eq`-zero-style match.

    Args:
        session: Async DB session.
        tenant_id: Tenant being evaluated.
        criteria_and_conditions: One (op, compiled_conditions) pair per
            criteria document being evaluated this run. Consumed twice (once
            per loop below), so callers must pass a list/tuple, not a
            one-shot generator.

    Returns:
        The full candidate user_id set.
    """
    universe: set[UUID] = set()
    for _, compiled_conditions in criteria_and_conditions:
        for compiled in compiled_conditions:
            universe |= compiled.values.keys()

    if any(_matches_absent_profile(op, cc) for op, cc in criteria_and_conditions):
        result = await session.execute(select(User.id).where(User.tenant_id == tenant_id))
        universe |= {row[0] for row in result.all()}
    return universe


def _resolve_group_winners(
    segments: list[Segment],
    ops_by_segment: dict[UUID, str],
    compiled_by_segment: dict[UUID, list[_CompiledCondition]],
    universe: set[UUID],
) -> dict[UUID, set[UUID]]:
    """Resolve, per user, the single winning segment in each exclusive group.

    Segments are walked in `(-priority, created_at, id)` order (highest
    priority first; ties broken by oldest `created_at`, then `id`, for
    determinism). For each user, the first matching segment in that order
    wins its group; the user is then skipped for every other segment sharing
    that `group_id` (exclusive within a group) but is still evaluated against
    every OTHER group (a user can win in many groups simultaneously).

    Args:
        segments: Every dynamic segment for this tenant (poisoned segments
            already excluded by the caller).
        ops_by_segment: segment_id -> its criteria's `op` ("AND"/"OR").
        compiled_by_segment: segment_id -> its precompiled conditions.
        universe: Candidate user ids to evaluate (see `_load_candidate_universe`).

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
            if _matches(ops_by_segment[seg.id], compiled_by_segment[seg.id], user_id):
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
    second row for the same pair would violate that constraint. There is no
    `tenant_id` column on `user_segments`; the tenant boundary is enforced
    one level up, by only ever calling this with a `segment` row that was
    itself fetched scoped to `tenant_id` (NFR-0220).

    Args:
        session: Async DB session.
        segment: The segment being recomputed.
        desired: User ids whose criteria currently match this segment.

    Returns:
        {"added": N, "removed": M, "member_count": len(desired)} — member_count
        is the criteria-desired count; manual-only members are not included.

    Side effects:
        Bulk-inserts new `UserSegment(source='criteria')` rows (in a canonical
        user_id-sorted order) and issues a bulk delete for stale criteria
        rows. Does not flush/commit.
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

    if to_add:
        # Core bulk insert (not per-row ORM `session.add`) — one round trip
        # for the whole batch. sorted() gives a canonical per-user insert
        # order (independent of set-iteration order) — same rationale as the
        # `Segment.id` FOR UPDATE lock order above: acquiring/inserting
        # contended rows in a fixed order across concurrent transactions
        # reduces deadlock risk, here when multiple segments' deltas touch
        # overlapping users.
        await session.execute(
            insert(UserSegment),
            [
                {
                    "user_id": user_id,
                    "segment_id": segment.id,
                    "source": USER_SEGMENT_SOURCE_CRITERIA,
                }
                for user_id in sorted(to_add)
            ],
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
) -> dict[UUID, dict[str, int]]:
    """Recompute every dynamic segment's membership for one tenant.

    Algorithm (spec §4): lock + collect dynamic segments, compute each
    distinct metric key once, evaluate criteria per candidate user, resolve
    highest-priority winner per exclusive group, diff against
    `source='criteria'` rows (manual rows untouched), apply the delta, stamp
    `last_evaluated_at`, and audit-log every segment whose membership changed.

    Args:
        session: Async DB session. The caller owns the transaction/commit.
        tenant_id: Tenant to recompute (NFR-0220 — every query stays scoped).
        now: Evaluation instant threaded through every metric computation AND
            stamped onto `Segment.last_evaluated_at`. Defaults to the current
            UTC instant, computed ONCE here so the whole recompute is
            internally consistent; passing an explicit (e.g. historical)
            value backdates `last_evaluated_at` to that instant — useful for
            deterministic/reproducible test runs, but callers driving real
            recomputes should leave this as the default.

    Returns:
        Mapping of segment_id -> {"added": int, "removed": int,
        "member_count": int}. Static (criteria-NULL) segments are absent.
        Also absent: any segment whose `criteria` fails DSL validation, AND
        every other segment sharing its `group_id` — poison isolation
        quarantines the WHOLE exclusive group, not just the poisoned
        segment, because exclusivity only holds when every segment in the
        group was evaluated together; leaving the group's membership
        stale-but-internally-consistent beats recomputing some tiers
        fresh while leaving others stale (which could let one user hold
        two tiers of the same lens at once). All quarantined segments are
        left completely untouched (no writes, no stamp, no audit).

    Side effects:
        Inserts/deletes `user_segments` rows with `source='criteria'`, sets
        `Segment.last_evaluated_at`, writes one `audit_log` row per changed
        segment (action `segment.recomputed`, actor system), and flushes the
        session. Never commits. Locks the tenant's dynamic segment rows
        `FOR UPDATE` for the duration — see the module docstring's
        concurrency note.
    """
    effective_now = now or datetime.now(UTC)

    # FOR UPDATE in canonical (id) order: mirrors rewards/outbox.py's locking
    # pattern. This serializes concurrent recomputes of the SAME tenant onto
    # one at a time (a second caller blocks here until the first commits),
    # so two overlapping recomputes never race to insert/delete the same
    # user_segments rows for the same segment.
    candidate_segments = (
        (
            await session.execute(
                select(Segment)
                .where(Segment.tenant_id == tenant_id, Segment.criteria.is_not(None))
                .order_by(Segment.id)
                .with_for_update()
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

    parsed: dict[UUID, SegmentCriteria] = {}
    for seg in segments:
        try:
            parsed[seg.id] = SegmentCriteria.model_validate(seg.criteria)
        except ValidationError as exc:
            # Poison-criteria isolation: a segment whose stored criteria no
            # longer parses (hand-edited row, DSL version drift, etc) must
            # not take down the whole tenant's recompute. Skip it — so its
            # existing membership (manual or stale criteria rows) is left
            # exactly as-is, and it never appears in the returned summary.
            log.warning(
                "segment_criteria_invalid",
                segment_id=str(seg.id),
                tenant_id=str(tenant_id),
                error=str(exc),
            )

    # Whole-GROUP quarantine, not just the poisoned segment: exclusivity
    # within a group means a lower-priority segment's "not desired" outcome
    # is only correct relative to a higher-priority segment that DID get
    # evaluated. If Gold is poisoned and skipped alone, Bronze would stop
    # being suppressed by Gold's (unknown) match — a user could then hold
    # BOTH a stale Gold row and a freshly added Bronze row in the same
    # exclusive group, reaching any segment-bound reward rule twice. Stale
    # but internally consistent (the whole group frozen at its last-known
    # membership) beats fresh but contradictory (some tiers recomputed,
    # others not, in the same exclusive lens). So any segment sharing a
    # group_id with a poisoned segment is ALSO left untouched this run.
    poisoned_group_ids = {seg.group_id for seg in segments if seg.id not in parsed}
    valid_segments = [
        seg for seg in segments if seg.id in parsed and seg.group_id not in poisoned_group_ids
    ]
    if poisoned_group_ids:
        log.warning(
            "segment_group_quarantined",
            tenant_id=str(tenant_id),
            group_ids=[str(g) for g in poisoned_group_ids],
        )
    if not valid_segments:
        return {}

    keys: set[MetricKey] = {
        _key_for_condition(cond) for criteria in parsed.values() for cond in criteria.conditions
    }
    values_by_key = await _compute_all_metric_keys(session, tenant_id, keys, effective_now)

    compiled_by_segment: dict[UUID, list[_CompiledCondition]] = {
        seg.id: [_compile_condition(cond, values_by_key) for cond in parsed[seg.id].conditions]
        for seg in valid_segments
    }
    ops_by_segment: dict[UUID, str] = {seg.id: parsed[seg.id].op for seg in valid_segments}

    universe = await _load_candidate_universe(
        session,
        tenant_id,
        [(ops_by_segment[seg.id], compiled_by_segment[seg.id]) for seg in valid_segments],
    )
    winners = _resolve_group_winners(valid_segments, ops_by_segment, compiled_by_segment, universe)

    summary: dict[UUID, dict[str, int]] = {}
    total_added = 0
    total_removed = 0
    for seg in valid_segments:
        result = await _apply_segment_delta(session, seg, winners[seg.id])
        seg.last_evaluated_at = effective_now
        summary[seg.id] = result
        total_added += result["added"]
        total_removed += result["removed"]
        if result["added"] + result["removed"] > 0:
            record_audit_for_system(
                session,
                tenant_id=tenant_id,
                action="segment.recomputed",
                entity_type="segment",
                entity_id=str(seg.id),
                # Shallow-copy: `after_state` must not alias the same dict
                # object stored in `summary` (a footgun if either were later
                # mutated before the audit row's JSONB value is serialized).
                after_state=dict(result),
            )

    await session.flush()
    log.info(
        "segments_recomputed",
        tenant_id=str(tenant_id),
        segments=len(valid_segments),
        users=len(universe),
        added=total_added,
        removed=total_removed,
    )
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
        widening as `recompute_tenant` (see `_load_candidate_universe`), so
        an lte/eq-zero-style preview correctly counts inactive users.
    """
    effective_now = now or datetime.now(UTC)
    keys = {_key_for_condition(cond) for cond in criteria.conditions}
    values_by_key = await _compute_all_metric_keys(session, tenant_id, keys, effective_now)
    compiled_conditions = [_compile_condition(cond, values_by_key) for cond in criteria.conditions]
    universe = await _load_candidate_universe(
        session, tenant_id, [(criteria.op, compiled_conditions)]
    )
    return sum(1 for user_id in universe if _matches(criteria.op, compiled_conditions, user_id))
