"""Segment-group service — admin CRUD for the segmentation "lens" (Task 6).

A `SegmentGroup` is the exclusive-tier container a `Segment` belongs to (e.g.
"Customer Loyalty" holding Bronze/Silver/Gold). Mirrors the structure of
`app.modules.segments.service` (tenant assert, flush, narrowed IntegrityError
handler, `record_audit_for_admin`). Deletion is guarded: system-seeded groups
can't be removed, and a group still holding segments can't be either — the
caller must move or delete those segments first (Task 7 wires that up).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.segments.schemas import SegmentGroupCreateRequest
from app.shared.exceptions import AppHTTPException, TenantNotFound
from app.shared.models import Segment, SegmentGroup, Tenant

# Postgres SQLSTATE for a unique-constraint violation — the only IntegrityError
# cause create_group() should translate into a 409; anything else is a real
# bug and must not be swallowed (mirrors segments/service.py's narrowed handler).
_UNIQUE_VIOLATION_SQLSTATE = "23505"


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


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
    await _assert_tenant_exists(session, request.tenant_id)

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
        if sqlstate != _UNIQUE_VIOLATION_SQLSTATE:
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
            as 404, never 403, so tenant existence is never leaked.
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
    result = await session.execute(
        select(SegmentGroup).where(SegmentGroup.id == group_id, SegmentGroup.tenant_id == tenant_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise AppHTTPException(404, "segment_group_not_found", "Segment group not found.")

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
            "This segment group still has segments assigned to it.",
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
