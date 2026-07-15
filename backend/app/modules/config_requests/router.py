"""Config-governance FastAPI router — maker-checker (Pricing v2 Epic 22).

Makers (platform-admin) propose / revise / resubmit / withdraw; checkers
(config-approver) approve / request-changes. `tenant_id` is an explicit query
param (admins are cross-tenant), matching the pricing/limits admin routers.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.admin_profiles import resolve_admin_names
from app.modules.config_requests.schemas import (
    ConfigChangeCommentRequest,
    ConfigChangeProposeRequest,
    ConfigChangeRequestOut,
    ConfigChangeReviseRequest,
    ConfigReviewOut,
    ConfigRevisionOut,
)
from app.modules.config_requests.service import (
    approve_config_request,
    get_config_request,
    list_config_requests,
    propose_config_change,
    request_config_changes,
    resubmit_config_request,
    revise_config_request,
    withdraw_config_request,
)

router = APIRouter(prefix="/api/v1/config-requests", tags=["config-governance"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _attach_admin_names(session: AsyncSession, outs: list[ConfigChangeRequestOut]) -> None:
    """Resolve maker/checker/reviewer subs → display names on the OUT objects.

    So the UI renders human names, never bare IDs. Unresolved subs stay None
    (the client falls back to a shortened id).
    """
    subs: set[str] = set()
    for out in outs:
        subs.add(out.maker_admin_id)
        if out.checker_admin_id:
            subs.add(out.checker_admin_id)
        subs.update(r.actor_admin_id for r in out.reviews)
    names = await resolve_admin_names(session, subs)
    for out in outs:
        out.maker_admin_name = names.get(out.maker_admin_id)
        out.checker_admin_name = names.get(out.checker_admin_id) if out.checker_admin_id else None
        for review in out.reviews:
            review.actor_admin_name = names.get(review.actor_admin_id)


async def _out(session: AsyncSession, result: object) -> ConfigChangeRequestOut:
    """Validate one request ORM row to its OUT + attach admin display names."""
    out = ConfigChangeRequestOut.model_validate(result)
    await _attach_admin_names(session, [out])
    return out


@router.post("", response_model=ConfigChangeRequestOut, status_code=201)
async def post_propose(
    request: ConfigChangeProposeRequest,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Maker proposes a config create/delete → PENDING (no config write yet)."""
    result = await propose_config_change(
        session, request, tenant_id=tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _out(session, result)


@router.get("", response_model=list[ConfigChangeRequestOut])
async def get_requests(
    tenant_id: UUID,
    status_filter: str | None = None,
    config_type: str | None = None,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[ConfigChangeRequestOut]:
    """List a tenant's config-change requests (optionally filtered by status/type)."""
    _ = admin
    requests = await list_config_requests(
        session, tenant_id, status=status_filter, config_type=config_type
    )
    outs = [ConfigChangeRequestOut.model_validate(r) for r in requests]
    await _attach_admin_names(session, outs)
    return outs


@router.get("/{request_id}", response_model=ConfigChangeRequestOut)
async def get_request(
    request_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Fetch one request with its full review thread."""
    _ = admin
    request, reviews, revisions = await get_config_request(session, request_id, tenant_id)
    out = ConfigChangeRequestOut.model_validate(request)
    out.reviews = [ConfigReviewOut.model_validate(r) for r in reviews]
    out.revisions = [ConfigRevisionOut.model_validate(r) for r in revisions]
    await _attach_admin_names(session, [out])
    return out


@router.post("/{request_id}/approve", response_model=ConfigChangeRequestOut)
async def post_approve(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("config-approver")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Checker approves a PENDING request → applies the config → APPLIED."""
    result = await approve_config_request(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _out(session, result)


@router.post("/{request_id}/request-changes", response_model=ConfigChangeRequestOut)
async def post_request_changes(
    request_id: UUID,
    tenant_id: UUID,
    body: ConfigChangeCommentRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("config-approver")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Checker requests changes (mandatory comment) → CHANGES_REQUESTED."""
    result = await request_config_changes(
        session,
        request_id,
        tenant_id,
        admin=admin,
        comment=body.comment,
        ip_address=_client_ip(fastapi_request),
    )
    return await _out(session, result)


@router.patch("/{request_id}", response_model=ConfigChangeRequestOut)
async def patch_revise(
    request_id: UUID,
    tenant_id: UUID,
    body: ConfigChangeReviseRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Original maker edits a CHANGES_REQUESTED request's payload (bumps revision)."""
    result = await revise_config_request(
        session,
        request_id,
        tenant_id,
        admin=admin,
        payload=body.payload,
        ip_address=_client_ip(fastapi_request),
    )
    return await _out(session, result)


@router.post("/{request_id}/resubmit", response_model=ConfigChangeRequestOut)
async def post_resubmit(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Original maker resubmits a CHANGES_REQUESTED request → PENDING."""
    result = await resubmit_config_request(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _out(session, result)


@router.post("/{request_id}/withdraw", response_model=ConfigChangeRequestOut)
async def post_withdraw(
    request_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ConfigChangeRequestOut:
    """Original maker abandons a non-terminal request → WITHDRAWN."""
    result = await withdraw_config_request(
        session, request_id, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return await _out(session, result)
