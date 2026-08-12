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

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.segments._common import (
    UNIQUE_VIOLATION_SQLSTATE,
    assert_tenant_exists,
    load_group_or_404,
)
from app.modules.segments.criteria import ALL_METRICS, TRANSACTIONAL_METRICS, WINDOWED_METRICS
from app.modules.segments.schemas import (
    MetricInfo,
    SegmentCreateRequest,
    SegmentUpdateRequest,
)
from app.shared.exceptions import AppHTTPException, UserNotFound
from app.shared.models import Segment, User, UserSegment

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


async def update_segment(
    session: AsyncSession,
    segment_id: UUID,
    tenant_id: UUID,
    request: SegmentUpdateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> Segment:
    """Update a segment's description, group, priority, and/or criteria.

    Only fields explicitly present in the request are touched — distinguished
    via `request.model_fields_set`, so an omitted field is left alone even
    though its default happens to equal `None`/`False`. Clearing criteria
    (turning a dynamic segment static) requires the explicit
    `clear_criteria=True` flag (see `SegmentUpdateRequest`'s docstring).

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
            `segment_group_not_found` when a `group_id` move target doesn't
            resolve inside the tenant; 409 `segment_protected` when a
            `group_id` move is attempted on an `is_system` segment — system
            tiers stay in the lens they were seeded into.

    Side effects:
        Updates the `segments` row and, if anything actually changed, writes
        one `segment.updated` audit row capturing only the changed fields'
        before/after values.
    """
    segment = (
        await session.execute(
            select(Segment).where(Segment.id == segment_id, Segment.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if segment is None:
        raise AppHTTPException(404, "segment_not_found", "Segment not found.")

    fields_set = request.model_fields_set

    # Validate the group move BEFORE mutating anything, so a rejected PATCH
    # (system-protected, or an unknown target group) never leaves the
    # segment partially updated. The `request.group_id is not None` check is
    # inside this `if`, not hoisted to a separate bool, so mypy narrows
    # `request.group_id` to `UUID` for the `load_group_or_404` call below.
    target_group = None
    if "group_id" in fields_set and request.group_id is not None:
        if segment.is_system:
            raise AppHTTPException(
                409,
                "segment_protected",
                "System segments cannot change group — they stay in their seeded lens.",
            )
        target_group = await load_group_or_404(session, request.group_id, tenant_id)

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    if target_group is not None and target_group.id != segment.group_id:
        before["group_id"] = str(segment.group_id)
        segment.group_id = target_group.id
        after["group_id"] = str(target_group.id)

    if "description" in fields_set and request.description != segment.description:
        before["description"] = segment.description
        segment.description = request.description
        after["description"] = request.description

    if (
        "priority" in fields_set
        and request.priority is not None
        and request.priority != segment.priority
    ):
        before["priority"] = segment.priority
        segment.priority = request.priority
        after["priority"] = request.priority

    if request.clear_criteria:
        if segment.criteria is not None:
            before["criteria"] = segment.criteria
            segment.criteria = None
            after["criteria"] = None
    elif "criteria" in fields_set and request.criteria is not None:
        new_criteria = request.criteria.model_dump()
        if segment.criteria != new_criteria:
            before["criteria"] = segment.criteria
            segment.criteria = new_criteria
            after["criteria"] = new_criteria

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
