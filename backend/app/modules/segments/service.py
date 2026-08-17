"""Segments service — cohort definitions (static + dynamic) + membership.

Used by the rules engine to filter candidate rules to users in a
specific segment (Rule.segment_id) and by the multipliers service to
target reward boosts at a cohort.

The membership lookup is hot-path — `user_is_in_segment` is called
from `_find_candidate_rules` for every rule that has a segment binding.
A composite index on user_segments(user_id, segment_id) backs it.

Task 7 wires in dynamic segments: `create_segment`/`update_segment` accept a
`criteria` document (validated by `app.modules.segments.criteria.SegmentCriteria`)
and a `group_id`/`priority` for the exclusive-tier evaluation the batch
evaluator (`evaluator.py`) performs. This module stays CRUD-only — the
evaluator, metric registry, and preview/recompute plumbing live elsewhere so
this file doesn't grow into a second copy of the evaluation engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.segments._common import (
    UNIQUE_VIOLATION_SQLSTATE,
    assert_tenant_exists,
    load_group_or_404,
)
from app.modules.segments.criteria import (
    ALL_METRICS,
    TRANSACTIONAL_METRICS,
    WINDOWED_METRICS,
    SegmentCriteria,
)
from app.modules.segments.evaluator import preview_criteria
from app.modules.segments.schemas import (
    MetricInfo,
    SegmentCreateRequest,
    SegmentUpdateRequest,
)
from app.shared.exceptions import AppHTTPException, UserNotFound
from app.shared.models import BonusMultiplier, Rule, Segment, User, UserSegment

# -----------------------------------------------------------------------------
# CRUD
# -----------------------------------------------------------------------------


async def create_segment(
    session: AsyncSession,
    request: SegmentCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> Segment:
    """Create a new segment, static or dynamic, inside a group.

    Args:
        session: Async DB session (committed here).
        request: The validated create payload. `request.group_id` must name
            a group belonging to `request.tenant_id` (404 otherwise —
            `load_group_or_404` never leaks cross-tenant existence).
            `request.criteria`, when present, makes the segment dynamic.
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Returns:
        The created Segment.

    Raises:
        TenantNotFound: `request.tenant_id` is unknown.
        AppHTTPException: 404 `segment_group_not_found` when `group_id`
            doesn't resolve inside the tenant; 409 `segment_already_exists`
            when the insert violates the segment-name unique constraint,
            which is now scoped per (tenant, group) — not tenant-wide — so
            the same name is free to reuse in a different group. Any other
            IntegrityError propagates instead of being misreported as a
            duplicate-name conflict.
    """
    await assert_tenant_exists(session, request.tenant_id)
    group = await load_group_or_404(session, request.group_id, request.tenant_id)

    segment = Segment(
        tenant_id=request.tenant_id,
        group_id=group.id,
        name=request.name,
        description=request.description,
        priority=request.priority,
        criteria=request.criteria.model_dump() if request.criteria is not None else None,
    )
    session.add(segment)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate != UNIQUE_VIOLATION_SQLSTATE:
            raise
        raise AppHTTPException(
            409,
            "segment_already_exists",
            "A segment with this name already exists within this group.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="segment.created",
            entity_type="segment",
            entity_id=str(segment.id),
            after_state={"name": segment.name},
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(segment)
    return segment


def _audit_value(value: Any) -> Any:
    """Coerce one ORM attribute value into a JSON-safe form for audit snapshots.

    The `audit_log.before_state`/`after_state` columns are JSONB written
    through asyncpg with no custom JSON encoder configured, so anything not
    natively `json.dumps`-able (a `UUID`, a `datetime`) must be pre-stringified
    here rather than handed to `AuditLog` as-is.

    Args:
        value: The raw attribute value (already read off the ORM instance).

    Returns:
        `str(value)` for a `UUID`, `value.isoformat()` for a `datetime`,
        otherwise `value` unchanged (already JSON-native: str, int, dict, None).
    """
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _apply_changes(
    segment: Segment, changes: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a field->new-value mapping to `segment`, skipping true no-ops.

    The caller is responsible for deciding WHICH fields belong in `changes`
    and what their final value should be (group-move validation, the
    clear_criteria/criteria exclusivity, etc. — see `update_segment`); this
    helper's only job is "for each candidate change, if the new value differs
    from the current one, set it and record it," so that logic isn't repeated
    once per field.

    Args:
        segment: The ORM instance mutated in place.
        changes: Mapping of `Segment` attribute name -> desired new value.

    Returns:
        (before, after) — audit-ready dicts (via `_audit_value`) containing
        only the subset of `changes` whose value actually differed from the
        segment's current one.
    """
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, new_value in changes.items():
        old_value = getattr(segment, field)
        if old_value == new_value:
            continue
        before[field] = _audit_value(old_value)
        setattr(segment, field, new_value)
        after[field] = _audit_value(new_value)
    return before, after


async def update_segment(
    session: AsyncSession,
    segment_id: UUID,
    tenant_id: UUID,
    request: SegmentUpdateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> Segment:
    """Update a segment's name, description, group, priority, and/or criteria.

    Only fields explicitly present in the request are touched — distinguished
    via `request.model_fields_set`, so an omitted field is left alone even
    though its default happens to equal `None`/`False`. `description` honours
    an explicit `null` as "clear it"; criteria does NOT — clearing criteria
    (turning a dynamic segment static) requires the explicit
    `clear_criteria=True` flag (see `SegmentUpdateRequest`'s docstring).
    Clearing criteria does NOT remove the segment's existing `criteria`-sourced
    `user_segments` rows — membership computed under the old criteria is
    frozen in place (no longer refreshed by the evaluator, since a
    criteria-NULL segment is invisible to `recompute_tenant`'s query) until an
    admin manually removes those members; this mirrors how a static segment's
    membership always behaves and avoids a surprise mass-removal as a side
    effect of a criteria edit.

    A `group_id` move is a no-op — validated or not, audited or not — whenever
    it names the segment's CURRENT group; only an ACTUAL move (a different
    target group) is checked against `is_system` and against
    `load_group_or_404`. This lets a client PATCH `group_id` unconditionally
    (e.g. re-submitting a whole form) without tripping the system-segment
    guard on a value that wouldn't have changed anything anyway. A `name`
    rename, by contrast, is allowed even for an `is_system` segment — the
    flag only protects deletion and group moves.

    Args:
        session: Async DB session (committed here).
        segment_id: The segment to update.
        tenant_id: Scope — a segment belonging to another tenant is reported
            as 404, never 403 (no existence leak).
        request: The validated PATCH payload.
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Returns:
        The updated Segment.

    Raises:
        AppHTTPException: 404 `segment_not_found` when the segment doesn't
            exist in this tenant (including cross-tenant); 404
            `segment_group_not_found` when a `group_id` MOVE target doesn't
            resolve inside the tenant; 409 `segment_protected` when a
            `group_id` MOVE is attempted on an `is_system` segment — system
            tiers stay in the lens they were seeded into; 409
            `segment_already_exists` when a `name` rename collides with the
            unique (tenant, group, name) constraint — same error the create
            path raises on a duplicate name within the same group.

    Side effects:
        Updates the `segments` row. If criteria actually changed (set,
        replaced, or cleared), also resets `last_evaluated_at` to NULL — the
        previous timestamp described membership computed under the OLD
        criteria, which is now stale; the admin UI renders a NULL
        `last_evaluated_at` on a dynamic segment as "pending recompute" until
        the next evaluator run. If anything changed at all, writes one
        `segment.updated` audit row capturing only the changed fields'
        before/after values (including `last_evaluated_at` when it was reset).
    """
    segment = (
        await session.execute(
            select(Segment).where(Segment.id == segment_id, Segment.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if segment is None:
        raise AppHTTPException(404, "segment_not_found", "Segment not found.")

    fields_set = request.model_fields_set
    changes: dict[str, Any] = {}

    # Only a REAL move (a different target group) is validated at all — see
    # the docstring's "no-op" note. This also means re-submitting the
    # segment's own current group_id never trips the is_system guard below.
    if (
        "group_id" in fields_set
        and request.group_id is not None
        and request.group_id != segment.group_id
    ):
        if segment.is_system:
            raise AppHTTPException(
                409,
                "segment_protected",
                "System segments cannot change group — they stay in their seeded lens.",
            )
        target_group = await load_group_or_404(session, request.group_id, tenant_id)
        changes["group_id"] = target_group.id

    if "name" in fields_set and request.name is not None:
        changes["name"] = request.name

    if "description" in fields_set:
        changes["description"] = request.description

    if "priority" in fields_set and request.priority is not None:
        changes["priority"] = request.priority

    if request.clear_criteria:
        changes["criteria"] = None
    elif "criteria" in fields_set and request.criteria is not None:
        changes["criteria"] = request.criteria.model_dump()

    before, after = _apply_changes(segment, changes)

    if "criteria" in after:
        # Criteria actually changed value — the evaluator's next recompute
        # (or lack thereof, for a newly-static segment) makes the existing
        # last_evaluated_at stamp describe a stale, no-longer-relevant run.
        if segment.last_evaluated_at is not None:
            before["last_evaluated_at"] = _audit_value(segment.last_evaluated_at)
            after["last_evaluated_at"] = None
        segment.last_evaluated_at = None

    if "name" in after:
        # A rename is the only field here that can violate a DB constraint
        # (uq_segments_name_per_group) — flush it alone, before writing the
        # audit row, so a collision rolls back cleanly without an audit entry
        # describing a change that never actually landed.
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if sqlstate != UNIQUE_VIOLATION_SQLSTATE:
                raise
            raise AppHTTPException(
                409,
                "segment_already_exists",
                "A segment with this name already exists within this group.",
            ) from exc

    if admin is not None and after:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="segment.updated",
            entity_type="segment",
            entity_id=str(segment.id),
            before_state=before,
            after_state=after,
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(segment)
    return segment


async def delete_segment(
    session: AsyncSession,
    segment_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a segment, guarded against system segments and live bindings.

    A segment can only be removed once nothing else in the rules/rewards
    engine still points at it — a dangling `Rule.segment_id` or
    `BonusMultiplier.segment_id` would otherwise silently stop targeting
    anyone the next time either is evaluated, which is a much harder bug to
    notice than a 409 telling the admin to unbind it first (mirrors
    `delete_group`'s "still has segments" guard one level up).

    Args:
        session: Async DB session (committed here).
        segment_id: The segment to delete.
        tenant_id: Scope — a segment belonging to another tenant is reported
            as 404, never 403 (no existence leak).
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Raises:
        AppHTTPException: 404 `segment_not_found` when the segment doesn't
            exist in this tenant (including cross-tenant); 409
            `segment_protected` for an `is_system` segment; 409
            `segment_in_use` while any rule or bonus multiplier still
            references it.

    Side effects:
        Bulk-deletes the segment's `user_segments` memberships, then the
        `segments` row itself, and writes a `segment.deleted` audit row
        capturing name/group/is_system/member_count as `before_state`.
    """
    segment = (
        await session.execute(
            select(Segment).where(Segment.id == segment_id, Segment.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if segment is None:
        raise AppHTTPException(404, "segment_not_found", "Segment not found.")

    if segment.is_system:
        raise AppHTTPException(
            409,
            "segment_protected",
            "System segments cannot be deleted.",
        )

    rule_count = (
        await session.execute(
            select(func.count()).select_from(Rule).where(Rule.segment_id == segment_id)
        )
    ).scalar_one()
    multiplier_count = (
        await session.execute(
            select(func.count())
            .select_from(BonusMultiplier)
            .where(BonusMultiplier.segment_id == segment_id)
        )
    ).scalar_one()
    if rule_count > 0 or multiplier_count > 0:
        raise AppHTTPException(
            409,
            "segment_in_use",
            f"Segment is bound to {rule_count} rule(s) and {multiplier_count} multiplier(s).",
        )

    member_count = (
        await session.execute(
            select(func.count())
            .select_from(UserSegment)
            .where(UserSegment.segment_id == segment_id)
        )
    ).scalar_one()
    before_state = {
        "name": segment.name,
        "group_id": str(segment.group_id),
        "is_system": segment.is_system,
        "member_count": member_count,
    }

    # Memberships have no independent lifecycle once their segment is gone —
    # bulk-delete them first so the row delete below never trips an FK
    # constraint on `user_segments.segment_id`.
    await session.execute(delete(UserSegment).where(UserSegment.segment_id == segment_id))
    await session.delete(segment)

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="segment.deleted",
            entity_type="segment",
            entity_id=str(segment_id),
            before_state=before_state,
            ip_address=ip_address,
        )

    await session.commit()


async def list_segments_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[Segment]:
    """Return every segment in the tenant — newest first.

    Returns ORM instances (not `SegmentOut`) — serialization is the router's
    job, consolidating this module onto one layering style instead of some
    functions returning schemas and others returning models (Task 6 review
    note).
    """
    result = await session.execute(
        select(Segment).where(Segment.tenant_id == tenant_id).order_by(Segment.created_at.desc())
    )
    return list(result.scalars().all())


def list_metrics() -> list[MetricInfo]:
    """Return the criteria DSL's full metric vocabulary, sorted by name.

    Backs `GET /segments/metrics` — lets the admin UI's criteria builder
    populate a metric dropdown (and know which filters apply to each metric)
    without hard-coding the DSL vocabulary a second time.
    """
    return [
        MetricInfo(
            name=name,
            supports_txn_type=name in TRANSACTIONAL_METRICS,
            supports_window=name in WINDOWED_METRICS,
        )
        for name in sorted(ALL_METRICS)
    ]


# -----------------------------------------------------------------------------
# Preview + recompute (Task 7 review fixes: both now 404 on an unknown tenant)
# -----------------------------------------------------------------------------


async def preview_segment_criteria(
    session: AsyncSession, tenant_id: UUID, criteria: SegmentCriteria
) -> int:
    """Validate the tenant exists, then dry-run count criteria matches.

    Thin wrapper around `evaluator.preview_criteria`: the evaluator itself
    has no reason to know about tenant existence (every other caller reaches
    it with an already-validated tenant), but the public preview endpoint
    does — without this check an unknown `tenant_id` silently "matched" zero
    users instead of 404ing.

    Args:
        session: Async DB session.
        tenant_id: Tenant to evaluate against.
        criteria: The (not-yet-persisted) criteria document being previewed.

    Returns:
        The count of matching users.

    Raises:
        TenantNotFound: `tenant_id` is unknown.
    """
    await assert_tenant_exists(session, tenant_id)
    return await preview_criteria(session, tenant_id, criteria)


async def enqueue_recompute(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Validate + audit a manual recompute request. Does NOT enqueue the task.

    Deliberately stops short of calling `recompute_one_tenant.delay(...)` —
    invariant #6 (external calls happen after DB commit, never inside a
    transaction) means the Celery enqueue must happen strictly AFTER this
    function's `session.commit()` has returned, not from inside a service
    function whose caller might still be mid-transaction. The router calls
    this first, then — once it returns successfully — calls `.delay()` itself.

    Args:
        session: Async DB session (committed here).
        tenant_id: Tenant whose dynamic segments should be recomputed.
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Raises:
        TenantNotFound: `tenant_id` is unknown.

    Side effects:
        Writes a `segment.recompute_requested` audit row (entity_type
        "tenant", since this action targets every dynamic segment in the
        tenant, not one specific segment) and commits.
    """
    await assert_tenant_exists(session, tenant_id)

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="segment.recompute_requested",
            entity_type="tenant",
            entity_id=str(tenant_id),
            ip_address=ip_address,
        )

    await session.commit()


# -----------------------------------------------------------------------------
# Membership
# -----------------------------------------------------------------------------


async def add_user_to_segment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    segment_id: UUID,
    user_id: UUID,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> UserSegment:
    """Idempotently assign a user to a segment.

    Both segment and user must belong to the same tenant — cross-tenant
    pairings return 404 (no existence leak).
    """
    segment = (
        await session.execute(
            select(Segment).where(Segment.id == segment_id, Segment.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if segment is None:
        raise AppHTTPException(404, "segment_not_found", "Segment not found.")

    user = (
        await session.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if user is None:
        raise UserNotFound()

    # Idempotent: existing membership returns silently.
    existing = (
        await session.execute(
            select(UserSegment).where(
                UserSegment.user_id == user_id,
                UserSegment.segment_id == segment_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    membership = UserSegment(user_id=user_id, segment_id=segment_id)
    session.add(membership)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="segment.user_added",
            entity_type="segment",
            entity_id=str(segment_id),
            after_state={"user_id": str(user_id)},
            ip_address=ip_address,
        )

    await session.commit()
    return membership


async def user_is_in_segment(session: AsyncSession, *, user_id: UUID, segment_id: UUID) -> bool:
    """Hot-path membership check used by the evaluator + multiplier resolver."""
    result = await session.execute(
        select(UserSegment.id).where(
            UserSegment.user_id == user_id,
            UserSegment.segment_id == segment_id,
        )
    )
    return result.scalar_one_or_none() is not None
