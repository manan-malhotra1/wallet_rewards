"""Segments FastAPI router (admin-gated).

Two routers:
  - `router` (/api/v1/segments)
      - POST   /segments                     create a segment (static or dynamic)
      - GET    /segments                     list segments in tenant
      - GET    /segments/metrics             criteria DSL metric vocabulary (Task 7)
      - GET    /segments/member-counts       per-segment + per-group member counts (B1.4+)
      - POST   /segments/preview             dry-run criteria match count (Task 7)
      - POST   /segments/recompute           enqueue a tenant's dynamic recompute (Task 7)
      - PATCH  /segments/{id}                update a segment (Task 7)
      - POST   /segments/{id}/users          add a user to the segment
  - `groups_router` (/api/v1/segment-groups) — Task 6
      - POST   /segment-groups              create a segment group
      - GET    /segment-groups              list segment groups in tenant
      - DELETE /segment-groups/{id}         delete a segment group (guarded)

Route ORDER matters: FastAPI matches path operations in declaration order, so
every LITERAL path (`/metrics`, `/preview`, `/recompute`) is declared before
any path-parameter route on this router (`PATCH /{segment_id}`,
`POST /{segment_id}/users`) — otherwise a literal segment could be swallowed
by a path-parameter route sharing its HTTP method.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.segments.group_service import (
    create_group,
    delete_group,
    list_groups,
    member_counts,
)
from app.modules.segments.schemas import (
    AddUserToSegmentRequest,
    MemberCountsOut,
    MetricInfo,
    SegmentCreateRequest,
    SegmentGroupCreateRequest,
    SegmentGroupOut,
    SegmentOut,
    SegmentPreviewRequest,
    SegmentPreviewResponse,
    SegmentRecomputeResponse,
    SegmentUpdateRequest,
)
from app.modules.segments.service import (
    add_user_to_segment,
    create_segment,
    enqueue_recompute,
    list_metrics,
    list_segments_for_tenant,
    preview_segment_criteria,
    update_segment,
)

# `tasks.py` imports `celery.shared_task` at module scope, but by the time
# this router module loads, Celery is already in the FastAPI import graph
# via `payments.service` -> `rewards.outbox` (also a module-scope
# `shared_task` import) — so importing the task here at module scope is not
# the first thing to pull Celery into the process; no lazy-import is needed.
from app.modules.segments.tasks import recompute_one_tenant

router = APIRouter(prefix="/api/v1/segments", tags=["segments"])
groups_router = APIRouter(prefix="/api/v1/segment-groups", tags=["segments"])


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
    """Create a new segment. 409 on duplicate name within the target group."""
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
    segments = await list_segments_for_tenant(session, tenant_id)
    return [SegmentOut.model_validate(s) for s in segments]


@router.get("/metrics", response_model=list[MetricInfo])
async def get_segment_metrics(
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> list[MetricInfo]:
    """List the criteria DSL's metric vocabulary, sorted by name."""
    _ = admin
    return list_metrics()


@router.get("/member-counts", response_model=MemberCountsOut)
async def get_segment_member_counts(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> MemberCountsOut:
    """Per-segment (manual/criteria split) + per-group (distinct users) member counts."""
    _ = admin
    return await member_counts(session, tenant_id)


@router.post("/preview", response_model=SegmentPreviewResponse)
async def post_segment_preview(
    request: SegmentPreviewRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SegmentPreviewResponse:
    """Dry-run: count users a criteria document would currently match. 404 on unknown tenant."""
    _ = admin
    match_count = await preview_segment_criteria(session, request.tenant_id, request.criteria)
    return SegmentPreviewResponse(match_count=match_count)


@router.post("/recompute", response_model=SegmentRecomputeResponse, status_code=202)
async def post_segment_recompute(
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SegmentRecomputeResponse:
    """Enqueue an async recompute of every dynamic segment for one tenant.

    `enqueue_recompute` validates the tenant and commits its audit row
    FIRST; only once that has returned successfully do we call `.delay()` —
    the external Celery enqueue happens strictly after the DB commit
    (invariant #6), never from inside a still-open transaction.
    """
    await enqueue_recompute(session, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request))
    recompute_one_tenant.delay(str(tenant_id))
    return SegmentRecomputeResponse(status="enqueued")


@router.patch("/{segment_id}", response_model=SegmentOut)
async def patch_segment(
    segment_id: UUID,
    tenant_id: UUID,
    request: SegmentUpdateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SegmentOut:
    """Update a segment's description, group, priority, and/or criteria."""
    segment = await update_segment(
        session,
        segment_id,
        tenant_id,
        request,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return SegmentOut.model_validate(segment)


@router.post("/{segment_id}/users", status_code=201)
async def post_user_to_segment(
    segment_id: UUID,
    tenant_id: UUID,
    request: AddUserToSegmentRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
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


@groups_router.post("", response_model=SegmentGroupOut, status_code=201)
async def post_segment_group(
    request: SegmentGroupCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SegmentGroupOut:
    """Create a new segment group. 409 on duplicate name in the tenant."""
    group = await create_group(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return SegmentGroupOut.model_validate(group)


@groups_router.get("", response_model=list[SegmentGroupOut])
async def get_segment_groups(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[SegmentGroupOut]:
    """List every segment group in the tenant, name-ordered."""
    _ = admin
    groups = await list_groups(session, tenant_id)
    return [SegmentGroupOut.model_validate(g) for g in groups]


@groups_router.delete("/{group_id}", status_code=204)
async def remove_segment_group(
    group_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a segment group. 404 cross-tenant/unknown; 409 protected or non-empty."""
    await delete_group(
        session,
        group_id,
        tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
