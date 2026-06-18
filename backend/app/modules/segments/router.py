"""Segments FastAPI router (admin-gated).

Three routes:
  - POST /segments                      create a segment
  - GET  /segments                      list segments in tenant
  - POST /segments/{id}/users           add a user to the segment
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.segments.schemas import (
    AddUserToSegmentRequest,
    SegmentCreateRequest,
    SegmentOut,
)
from app.modules.segments.service import (
    add_user_to_segment,
    create_segment,
    list_segments_for_tenant,
)

router = APIRouter(prefix="/api/v1/segments", tags=["segments"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing."""
    return request.client.host if request.client else None


@router.post("", response_model=SegmentOut, status_code=201)
async def post_segment(
    request: SegmentCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SegmentOut:
    """Create a new segment. 409 on duplicate name in the tenant."""
    segment = await create_segment(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return SegmentOut.model_validate(segment)


@router.get("", response_model=list[SegmentOut])
async def get_segments(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[SegmentOut]:
    """List every segment in the tenant."""
    _ = admin
    return await list_segments_for_tenant(session, tenant_id)


@router.post("/{segment_id}/users", status_code=201)
async def post_user_to_segment(
    segment_id: UUID,
    tenant_id: UUID,
    request: AddUserToSegmentRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Assign a user to a segment. Idempotent."""
    membership = await add_user_to_segment(
        session,
        tenant_id=tenant_id,
        segment_id=segment_id,
        user_id=request.user_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return {
        "segment_id": str(membership.segment_id),
        "user_id": str(membership.user_id),
    }
