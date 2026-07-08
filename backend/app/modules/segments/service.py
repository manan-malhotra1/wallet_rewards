"""Segments service — static cohort definitions + membership.

Used by the rules engine to filter candidate rules to users in a
specific segment (Rule.segment_id) and by the multipliers service to
target reward boosts at a cohort.

The membership lookup is hot-path — `user_is_in_segment` is called
from `_find_candidate_rules` for every rule that has a segment binding.
A composite index on user_segments(user_id, segment_id) backs it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.segments.schemas import SegmentCreateRequest, SegmentOut
from app.shared.exceptions import (
    AppHTTPException,
    TenantNotFound,
    UserNotFound,
)
from app.shared.models import Segment, Tenant, User, UserSegment


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


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
    """Create a new segment. 409 on duplicate name within the tenant."""
    await _assert_tenant_exists(session, request.tenant_id)

    segment = Segment(
        tenant_id=request.tenant_id,
        name=request.name,
        description=request.description,
    )
    session.add(segment)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppHTTPException(
            409,
            "segment_already_exists",
            "A segment with this name already exists in the tenant.",
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


async def list_segments_for_tenant(session: AsyncSession, tenant_id: UUID) -> list[SegmentOut]:
    """Return every segment in the tenant — newest first."""
    result = await session.execute(
        select(Segment).where(Segment.tenant_id == tenant_id).order_by(Segment.created_at.desc())
    )
    return [SegmentOut.model_validate(s) for s in result.scalars().all()]


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
