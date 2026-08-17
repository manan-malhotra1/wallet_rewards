"""Segment-group service — admin CRUD for the segmentation "lens" (Task 6).

A `SegmentGroup` is the exclusive-tier container a `Segment` belongs to (e.g.
"Customer Loyalty" holding Bronze/Silver/Gold). Mirrors the structure of
`app.modules.segments.service` (tenant assert, flush, narrowed IntegrityError
handler, `record_audit_for_admin`). Deletion is guarded: system-seeded groups
can't be removed, and a group still holding segments can't be either — the
caller must move those segments to another group first, via `group_id` on
PATCH /segments (Task 7), or delete them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.segments._common import (
    UNIQUE_VIOLATION_SQLSTATE,
    assert_tenant_exists,
    load_group_or_404,
)
from app.modules.segments.schemas import (
    GroupMemberCount,
    MemberCountsOut,
    SegmentGroupCreateRequest,
    SegmentMemberCount,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import Segment, SegmentGroup, UserSegment
from app.shared.models.segments import USER_SEGMENT_SOURCE_CRITERIA, USER_SEGMENT_SOURCE_MANUAL


async def create_group(
    session: AsyncSession,
    request: SegmentGroupCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> SegmentGroup:
    """Create a new segment group.

    Args:
        session: Async DB session (committed here).
        request: The validated create payload.
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Returns:
        The created SegmentGroup.

    Raises:
        TenantNotFound: request.tenant_id is unknown.
        AppHTTPException: 409 `segment_group_name_taken` when the insert
            violates the (tenant_id, name) unique constraint. Any other
            IntegrityError propagates instead of being misreported as a
            duplicate-name conflict.

    Side effects:
        Inserts a `segment_groups` row and a `segment_group.created` audit row.
    """
    await assert_tenant_exists(session, request.tenant_id)

    group = SegmentGroup(
        tenant_id=request.tenant_id,
        name=request.name,
        description=request.description,
    )
    session.add(group)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate != UNIQUE_VIOLATION_SQLSTATE:
            raise
        raise AppHTTPException(
            409,
            "segment_group_name_taken",
            "A segment group with this name already exists in the tenant.",
        ) from exc

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="segment_group.created",
            entity_type="segment_group",
            entity_id=str(group.id),
            after_state={"name": group.name},
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(group)
    return group


async def list_groups(session: AsyncSession, tenant_id: UUID) -> list[SegmentGroup]:
    """Return every segment group in the tenant, name-ordered."""
    result = await session.execute(
        select(SegmentGroup).where(SegmentGroup.tenant_id == tenant_id).order_by(SegmentGroup.name)
    )
    return list(result.scalars().all())


async def delete_group(
    session: AsyncSession,
    group_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Delete a segment group.

    Args:
        session: Async DB session (committed here).
        group_id: The group to delete.
        tenant_id: Scope — a group belonging to another tenant is reported
            as 404, never 403, so a group's existence in another tenant is
            never leaked.
        admin: Acting admin — audited when present.
        ip_address: Caller IP for the audit record.

    Raises:
        AppHTTPException: 404 `segment_group_not_found` when the group
            doesn't exist in this tenant (including cross-tenant); 409
            `segment_group_protected` for system-seeded groups; 409
            `segment_group_not_empty` while any segment still references it.

    Side effects:
        Deletes the `segment_groups` row and adds a `segment_group.deleted`
        audit row capturing the group's name as `before_state`.
    """
    group = await load_group_or_404(session, group_id, tenant_id)

    if group.is_system:
        raise AppHTTPException(
            409,
            "segment_group_protected",
            "System segment groups cannot be deleted.",
        )

    segment_count = (
        await session.execute(
            select(func.count()).select_from(Segment).where(Segment.group_id == group_id)
        )
    ).scalar_one()
    if segment_count > 0:
        raise AppHTTPException(
            409,
            "segment_group_not_empty",
            f"This segment group still has {segment_count} segment(s) assigned. "
            "Move or delete them first.",
        )

    before_state = {"name": group.name}
    await session.delete(group)

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=tenant_id,
            action="segment_group.deleted",
            entity_type="segment_group",
            entity_id=str(group_id),
            before_state=before_state,
            ip_address=ip_address,
        )

    await session.commit()


# -----------------------------------------------------------------------------
# Member counts (Story B1.4+) — per-segment + per-group aggregates for the
# admin Segments page. Lives here (not service.py, already at this repo's
# ~400-line file-size guideline) rather than metrics.py, which is the
# criteria-DSL metric registry (a different concern — computed feature values
# per user for evaluation, not a membership-count read model).
# -----------------------------------------------------------------------------


async def member_counts(session: AsyncSession, tenant_id: UUID) -> MemberCountsOut:
    """Return per-segment and per-group membership counts for a tenant.

    Two grouped aggregate queries, no N+1: one joins `user_segments` ->
    `segments` and groups by `segment_id` for the total/manual/criteria
    split; the other groups by `segments.group_id` and counts DISTINCT
    `user_id` so a user assigned to two segments in the same group is
    counted once (see `GroupMemberCount`'s docstring). Neither query
    validates that `tenant_id` exists — mirrors `list_segments_for_tenant`
    and `list_groups`, which likewise just return an empty result for an
    unknown tenant rather than 404ing, since this is a read-only aggregate
    over an already tenant-scoped join, not a mutation.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope both aggregates to, via `Segment.tenant_id`.

    Returns:
        `MemberCountsOut` with both arrays omitting zero-member
        segments/groups (see each schema's docstring).
    """
    per_segment_stmt = (
        select(
            UserSegment.segment_id,
            func.count().label("total"),
            func.count()
            .filter(UserSegment.source == USER_SEGMENT_SOURCE_MANUAL)
            .label("manual"),
            func.count()
            .filter(UserSegment.source == USER_SEGMENT_SOURCE_CRITERIA)
            .label("criteria"),
        )
        .join(Segment, Segment.id == UserSegment.segment_id)
        .where(Segment.tenant_id == tenant_id)
        .group_by(UserSegment.segment_id)
    )
    per_group_stmt = (
        select(
            Segment.group_id,
            func.count(func.distinct(UserSegment.user_id)).label("distinct_users"),
        )
        .join(Segment, Segment.id == UserSegment.segment_id)
        .where(Segment.tenant_id == tenant_id)
        .group_by(Segment.group_id)
    )

    segment_rows = (await session.execute(per_segment_stmt)).all()
    group_rows = (await session.execute(per_group_stmt)).all()

    return MemberCountsOut(
        segments=[
            SegmentMemberCount(
                segment_id=row.segment_id, total=row.total, manual=row.manual, criteria=row.criteria
            )
            for row in segment_rows
        ],
        groups=[
            GroupMemberCount(group_id=row.group_id, distinct_users=row.distinct_users)
            for row in group_rows
        ],
    )
