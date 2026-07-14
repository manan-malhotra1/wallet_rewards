"""Config-governance service — the maker-checker workflow (Pricing v2 Epic 22).

Propose -> (approve | request-changes -> revise -> resubmit)* -> APPLIED, or
withdraw. Nothing is written to a real config table until APPLIED; the request
row and its append-only review thread persist across the whole loop.

Separation of duties: the checker (config-approver) MUST be a different admin
than the maker. Revise / resubmit / withdraw are the ORIGINAL maker only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.config_requests.apply import apply_config_request, build_create_schema
from app.modules.config_requests.schemas import ConfigChangeProposeRequest
from app.shared.exceptions import (
    AppHTTPException,
    ConfigRequestForbidden,
    ConfigRequestInvalidState,
    ConfigRequestNotFound,
    SelfApprovalForbidden,
    TenantNotFound,
)
from app.shared.models import (
    CONFIG_OP_CREATE,
    CONFIG_STATUS_APPLIED,
    CONFIG_STATUS_CHANGES_REQUESTED,
    CONFIG_STATUS_PENDING,
    CONFIG_STATUS_WITHDRAWN,
    CONFIG_TERMINAL_STATUSES,
    REVIEW_ACTION_APPROVED,
    REVIEW_ACTION_CHANGES_REQUESTED,
    REVIEW_ACTION_RESUBMITTED,
    REVIEW_ACTION_REVISED,
    REVIEW_ACTION_SUBMITTED,
    REVIEW_ACTION_WITHDRAWN,
    REVIEW_ROLE_CHECKER,
    REVIEW_ROLE_MAKER,
    ConfigChangeRequest,
    ConfigChangeReview,
    Tenant,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _load_request(
    session: AsyncSession, request_id: UUID, tenant_id: UUID, *, for_update: bool = False
) -> ConfigChangeRequest:
    """Load a tenant-scoped request, optionally locking it for a state change."""
    stmt = select(ConfigChangeRequest).where(
        ConfigChangeRequest.id == request_id,
        ConfigChangeRequest.tenant_id == tenant_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    request = result.scalar_one_or_none()
    if request is None:
        raise ConfigRequestNotFound()
    return request


def _add_review(
    session: AsyncSession,
    request: ConfigChangeRequest,
    *,
    actor_admin_id: str,
    actor_role: str,
    action: str,
    comment: str | None = None,
) -> None:
    """Append one entry to the request's review thread (append-only)."""
    session.add(
        ConfigChangeReview(
            tenant_id=request.tenant_id,
            request_id=request.id,
            actor_admin_id=actor_admin_id,
            actor_role=actor_role,
            action=action,
            comment=comment,
        )
    )


def _audit(
    session: AsyncSession,
    admin: AdminPrincipal,
    request: ConfigChangeRequest,
    action: str,
    ip_address: str | None,
) -> None:
    """Record an admin audit row for a request transition."""
    record_audit_for_admin(
        session,
        admin,
        tenant_id=request.tenant_id,
        action=action,
        entity_type="config_change_request",
        entity_id=str(request.id),
        after_state={
            "config_type": request.config_type,
            "operation": request.operation,
            "status": request.status,
            "revision": request.revision,
        },
        ip_address=ip_address,
    )


async def propose_config_change(
    session: AsyncSession,
    request_data: ConfigChangeProposeRequest,
    *,
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Maker proposes a config create/delete → PENDING, no config write yet.

    Raises:
        TenantNotFound (404).
        AppHTTPException (422): a create without a payload, a delete without a
            target, or a payload that fails its config type's create schema.
    """
    await _assert_tenant_exists(session, tenant_id)

    if request_data.operation == CONFIG_OP_CREATE:
        if request_data.payload is None:
            raise AppHTTPException(
                422, "config_request_payload_required", "A create proposal needs a payload."
            )
        # Fail fast on a malformed payload; store the normalised JSON form.
        schema = build_create_schema(request_data.config_type, request_data.payload)
        # Tenant isolation: the payload's own tenant must match the request scope.
        if getattr(schema, "tenant_id", tenant_id) != tenant_id:
            raise AppHTTPException(
                422,
                "config_request_tenant_mismatch",
                "The payload's tenant_id does not match the request tenant.",
            )
        payload = schema.model_dump(mode="json")
        target_config_id = None
    else:  # delete
        if request_data.target_config_id is None:
            raise AppHTTPException(
                422,
                "config_request_target_required",
                "A delete proposal needs a target_config_id.",
            )
        payload = None
        target_config_id = request_data.target_config_id

    request = ConfigChangeRequest(
        tenant_id=tenant_id,
        config_type=request_data.config_type,
        operation=request_data.operation,
        payload=payload,
        target_config_id=target_config_id,
        status=CONFIG_STATUS_PENDING,
        maker_admin_id=admin.id,
        revision=1,
    )
    session.add(request)
    await session.flush()
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_MAKER,
        action=REVIEW_ACTION_SUBMITTED,
    )
    _audit(session, admin, request, "config_request.proposed", ip_address)
    await session.commit()
    await session.refresh(request)
    return request


async def approve_config_request(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Checker approves a PENDING request → applies the config in one txn → APPLIED.

    Raises:
        ConfigRequestNotFound (404).
        SelfApprovalForbidden (409): the checker is the maker.
        ConfigRequestInvalidState (409): the request isn't PENDING.
        AppHTTPException: propagated from the underlying config write (e.g. 409
            unique collision), which rolls the whole transaction back.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != CONFIG_STATUS_PENDING:
        raise ConfigRequestInvalidState(request.status)
    if admin.id == request.maker_admin_id:
        raise SelfApprovalForbidden()

    # Stage the transition + review + audit BEFORE the config write. The config
    # service's commit persists all of it atomically; a collision rolls it back.
    request.status = CONFIG_STATUS_APPLIED
    request.checker_admin_id = admin.id
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_CHECKER,
        action=REVIEW_ACTION_APPROVED,
    )
    _audit(session, admin, request, "config_request.approved", ip_address)
    await apply_config_request(session, request, admin=admin, ip_address=ip_address)
    await session.refresh(request)
    return request


async def request_config_changes(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    comment: str,
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Checker requests changes on a PENDING request → CHANGES_REQUESTED (non-terminal).

    Raises:
        ConfigRequestNotFound (404).
        SelfApprovalForbidden (409): the checker is the maker.
        ConfigRequestInvalidState (409): the request isn't PENDING.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != CONFIG_STATUS_PENDING:
        raise ConfigRequestInvalidState(request.status)
    if admin.id == request.maker_admin_id:
        raise SelfApprovalForbidden()

    request.status = CONFIG_STATUS_CHANGES_REQUESTED
    request.checker_admin_id = admin.id
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_CHECKER,
        action=REVIEW_ACTION_CHANGES_REQUESTED,
        comment=comment,
    )
    _audit(session, admin, request, "config_request.changes_requested", ip_address)
    await session.commit()
    await session.refresh(request)
    return request


async def revise_config_request(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    payload: dict[str, Any],
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Original maker edits a CHANGES_REQUESTED request's payload; bumps revision.

    Raises:
        ConfigRequestNotFound (404).
        ConfigRequestForbidden (403): not the original maker.
        ConfigRequestInvalidState (409): not in CHANGES_REQUESTED.
        AppHTTPException (422): the new payload fails its create schema, or the
            request is a delete (no payload to edit).
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != CONFIG_STATUS_CHANGES_REQUESTED:
        raise ConfigRequestInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise ConfigRequestForbidden("Only the original maker may revise this request.")
    if request.operation != CONFIG_OP_CREATE:
        raise AppHTTPException(
            422, "config_request_not_editable", "A delete proposal has no payload to revise."
        )

    schema = build_create_schema(request.config_type, payload)
    request.payload = schema.model_dump(mode="json")
    request.revision += 1
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_MAKER,
        action=REVIEW_ACTION_REVISED,
    )
    _audit(session, admin, request, "config_request.revised", ip_address)
    await session.commit()
    await session.refresh(request)
    return request


async def resubmit_config_request(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Original maker resubmits a CHANGES_REQUESTED request → back to PENDING.

    Raises:
        ConfigRequestNotFound (404).
        ConfigRequestForbidden (403): not the original maker.
        ConfigRequestInvalidState (409): not in CHANGES_REQUESTED.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != CONFIG_STATUS_CHANGES_REQUESTED:
        raise ConfigRequestInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise ConfigRequestForbidden("Only the original maker may resubmit this request.")

    request.status = CONFIG_STATUS_PENDING
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_MAKER,
        action=REVIEW_ACTION_RESUBMITTED,
    )
    _audit(session, admin, request, "config_request.resubmitted", ip_address)
    await session.commit()
    await session.refresh(request)
    return request


async def withdraw_config_request(
    session: AsyncSession,
    request_id: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Original maker abandons a non-terminal request → WITHDRAWN (terminal).

    Raises:
        ConfigRequestNotFound (404).
        ConfigRequestForbidden (403): not the original maker.
        ConfigRequestInvalidState (409): the request is already terminal.
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status in CONFIG_TERMINAL_STATUSES:
        raise ConfigRequestInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise ConfigRequestForbidden("Only the original maker may withdraw this request.")

    request.status = CONFIG_STATUS_WITHDRAWN
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_MAKER,
        action=REVIEW_ACTION_WITHDRAWN,
    )
    _audit(session, admin, request, "config_request.withdrawn", ip_address)
    await session.commit()
    await session.refresh(request)
    return request


async def list_config_requests(
    session: AsyncSession, tenant_id: UUID, *, status: str | None = None
) -> list[ConfigChangeRequest]:
    """Return a tenant's config requests, newest-first, optionally by status."""
    stmt = select(ConfigChangeRequest).where(ConfigChangeRequest.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(ConfigChangeRequest.status == status)
    stmt = stmt.order_by(ConfigChangeRequest.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_config_request(
    session: AsyncSession, request_id: UUID, tenant_id: UUID
) -> tuple[ConfigChangeRequest, list[ConfigChangeReview]]:
    """Return a request with its full review thread (oldest-first)."""
    request = await _load_request(session, request_id, tenant_id)
    result = await session.execute(
        select(ConfigChangeReview)
        .where(ConfigChangeReview.request_id == request.id)
        .order_by(ConfigChangeReview.created_at.asc())
    )
    return request, list(result.scalars().all())
