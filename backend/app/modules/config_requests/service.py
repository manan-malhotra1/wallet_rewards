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

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.admin_profiles import record_admin
from app.modules.audit.service import record_audit_for_admin
from app.modules.config_requests.apply import (
    apply_config_request,
    config_scope,
    load_config_target,
    validate_band_payload,
)
from app.modules.config_requests.schemas import ConfigChangeProposeRequest
from app.shared.exceptions import (
    AppHTTPException,
    ConfigRequestAlreadyOpen,
    ConfigRequestForbidden,
    ConfigRequestInvalidState,
    ConfigRequestNotFound,
    ConfigRequestTargetNotFound,
    SelfApprovalForbidden,
    TenantNotFound,
)
from app.shared.models import (
    CONFIG_OP_CREATE,
    CONFIG_OP_DELETE,
    CONFIG_OP_UPDATE,
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
    ConfigChangeRevision,
    Tenant,
)

# A request still inside the maker-checker loop: the maker may approve/reject/
# withdraw or revise it, but MUST NOT stack another change on the same scope
# while it is open. APPLIED / WITHDRAWN are terminal and never block a re-propose.
_OPEN_STATUSES = (CONFIG_STATUS_PENDING, CONFIG_STATUS_CHANGES_REQUESTED)


def _normalise_create_payload(config_type: str, bands: list[BaseModel]) -> dict[str, Any]:
    """Serialise validated create-schema models into the stored payload shape.

    Multi-band types (pricing/commission) store `{"bands": [row, ...]}`; every
    other type is a single flat dict (its create schema), matching what
    `validate_band_payload` + `apply_config_request` expect on the way back.
    """
    from app.modules.config_requests.apply import MULTI_BAND_TYPES

    if config_type in MULTI_BAND_TYPES:
        return {"bands": [band.model_dump(mode="json") for band in bands]}
    return bands[0].model_dump(mode="json")


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


def _add_revision(
    session: AsyncSession,
    request: ConfigChangeRequest,
) -> None:
    """Append an immutable payload snapshot at the request's current revision.

    Called at propose (revision 1) and after each revise (bumped revision). The
    snapshot copies whatever `request.payload` currently holds (None for a
    delete proposal). Append-only — snapshots are never updated or deleted.
    """
    session.add(
        ConfigChangeRevision(
            tenant_id=request.tenant_id,
            request_id=request.id,
            revision=request.revision,
            payload=request.payload,
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


def _validate_payload(
    config_type: str, payload: dict[str, Any] | None, tenant_id: UUID
) -> tuple[dict[str, Any], list[BaseModel]]:
    """Validate a create/update payload and normalise it to the stored shape.

    A pricing/commission payload may be a multi-band schedule — every band and
    the band set are validated, and the canonical `{"bands": [...]}` form is
    always stored (a single band becomes a one-element list). Shared by the
    create and update propose paths (an update payload IS a full new config,
    identical in shape to create).

    Returns:
        The normalised payload dict AND the validated band models (the update
        path reads the first band's scope; create ignores the models).

    Raises:
        AppHTTPException (422): a missing payload, a schema failure, or a band
            whose tenant_id mismatches the request scope.
    """
    if payload is None:
        raise AppHTTPException(
            422, "config_request_payload_required", "This proposal needs a payload."
        )
    bands = validate_band_payload(config_type, payload)
    # Tenant isolation: every band's tenant must match the request scope.
    for band in bands:
        if getattr(band, "tenant_id", tenant_id) != tenant_id:
            raise AppHTTPException(
                422,
                "config_request_tenant_mismatch",
                "The payload's tenant_id does not match the request tenant.",
            )
    return _normalise_create_payload(config_type, bands), bands


async def _assert_update_scope_matches_target(
    session: AsyncSession,
    config_type: str,
    target_config_id: UUID,
    tenant_id: UUID,
    band: BaseModel,
) -> None:
    """Assert an update's payload keeps the scope of the live row it names.

    An update edits exactly ONE live config row: the payload's derived scope MUST
    equal that target row's scope. Otherwise an approval would atomically replace
    a DIFFERENT scope and leave the named config untouched. This is the config-
    governance trust boundary, and it is identical for propose and for revise —
    both load the target fresh (under the caller's lock, for revise) and compare
    scope keys — so the check lives here once.

    Args:
        band: The first validated create-schema band of the (possibly multi-band)
            payload; its scope is compared against the live target row's scope.

    Raises:
        ConfigRequestTargetNotFound (404): no such live row in this tenant.
        AppHTTPException (422): the payload's scope differs from the target's.
    """
    target = await load_config_target(session, config_type, target_config_id, tenant_id)
    if target is None:
        raise ConfigRequestTargetNotFound()
    if config_scope(config_type, band) != config_scope(config_type, target):
        raise AppHTTPException(
            422,
            "config_request_scope_mismatch",
            "The edit's scope must match the config being edited.",
        )


async def _request_scope(
    session: AsyncSession, request: ConfigChangeRequest
) -> tuple[object, ...] | None:
    """Resolve an existing request's config scope for the open-request guard.

    A create/update carries its scope in its payload (first band); a delete's
    scope lives on its live target row, loaded fresh. A delete whose target row
    is already gone has no resolvable scope and is treated as non-conflicting.

    Returns:
        The scope tuple, or None when it cannot be resolved (a delete with a
        missing target, or a create/update with no payload).
    """
    if request.operation == CONFIG_OP_DELETE:
        if request.target_config_id is None:
            return None
        target = await load_config_target(
            session, request.config_type, request.target_config_id, request.tenant_id
        )
        return None if target is None else config_scope(request.config_type, target)
    if not request.payload:
        return None
    bands = validate_band_payload(request.config_type, request.payload)
    return config_scope(request.config_type, bands[0])


async def _open_request_scope_conflict(
    session: AsyncSession,
    tenant_id: UUID,
    config_type: str,
    new_scope: tuple[object, ...] | None,
) -> bool:
    """True if an OPEN request already targets the same (tenant, type, scope).

    "Open" = PENDING or CHANGES_REQUESTED (still in the maker-checker loop). Each
    open request's scope is resolved the same way the new one is (payload for
    create/update, live target row for delete). Enforces one in-flight change per
    config scope so a maker can't stack duplicate pending edits.

    Returns:
        False when `new_scope` is None — a new delete whose target is absent has
        no scope to conflict on, and the apply-time 404 handles that path.
    """
    if new_scope is None:
        return False
    result = await session.execute(
        select(ConfigChangeRequest).where(
            ConfigChangeRequest.tenant_id == tenant_id,
            ConfigChangeRequest.config_type == config_type,
            ConfigChangeRequest.status.in_(_OPEN_STATUSES),
        )
    )
    for existing in result.scalars().all():
        if await _request_scope(session, existing) == new_scope:
            return True
    return False


async def propose_config_change(
    session: AsyncSession,
    request_data: ConfigChangeProposeRequest,
    *,
    tenant_id: UUID,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> ConfigChangeRequest:
    """Maker proposes a config create/update/delete → PENDING, no config write yet.

    An update carries BOTH the full new config (`payload`, validated exactly
    like a create) and the `target_config_id` of the live row being edited,
    which must exist in this tenant for the config type.

    Raises:
        TenantNotFound (404).
        ConfigRequestTargetNotFound (404): an update target that isn't here. A
            delete's target is NOT checked at propose — its scope is resolved
            from the live row at apply time, which 404s with the same code.
        AppHTTPException (422): a create/update without a payload, an
            update/delete without a target, or a payload that fails its schema.
    """
    await _assert_tenant_exists(session, tenant_id)

    if request_data.operation in (CONFIG_OP_CREATE, CONFIG_OP_UPDATE):
        payload, bands = _validate_payload(
            request_data.config_type, request_data.payload, tenant_id
        )
        target_config_id = None
        if request_data.operation == CONFIG_OP_UPDATE:
            # An update edits a live row: require the target, then — the
            # governance trust boundary — verify it exists and its scope matches
            # the edit's. Otherwise a request naming target X (scope A) could carry
            # a payload for scope B and silently replace B, leaving X untouched.
            if request_data.target_config_id is None:
                raise AppHTTPException(
                    422,
                    "config_request_target_required",
                    "An update proposal needs a target_config_id.",
                )
            await _assert_update_scope_matches_target(
                session,
                request_data.config_type,
                request_data.target_config_id,
                tenant_id,
                bands[0],
            )
            target_config_id = request_data.target_config_id
        new_scope: tuple[object, ...] | None = config_scope(request_data.config_type, bands[0])
    else:  # delete
        if request_data.target_config_id is None:
            raise AppHTTPException(
                422,
                "config_request_target_required",
                "A delete proposal needs a target_config_id.",
            )
        payload = None
        target_config_id = request_data.target_config_id
        # A delete's scope lives on its live target row; resolve it for the guard.
        # A missing target has no scope — the apply-time 404 handles that path, so
        # propose stays non-blocking (preserving the delete propose contract).
        delete_target = await load_config_target(
            session, request_data.config_type, target_config_id, tenant_id
        )
        new_scope = (
            None
            if delete_target is None
            else config_scope(request_data.config_type, delete_target)
        )

    # Trust boundary: one in-flight change per config scope. Reject a proposal
    # whose scope already has an OPEN (PENDING / CHANGES_REQUESTED) request — the
    # maker must resolve or revise that one first, not stack a duplicate.
    if await _open_request_scope_conflict(
        session, tenant_id, request_data.config_type, new_scope
    ):
        raise ConfigRequestAlreadyOpen()

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
    # Snapshot revision 1's payload so the whole version history is readable.
    _add_revision(session, request)
    _audit(session, admin, request, "config_request.proposed", ip_address)
    await record_admin(session, admin)
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
    await record_admin(session, admin)
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
    await record_admin(session, admin)
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
        ConfigRequestTargetNotFound (404): an update whose target row is gone.
        AppHTTPException (422): the new payload fails its create schema, carries a
            band for another tenant, moves an update's scope off its target, or
            the request is a delete (no payload to edit).
    """
    request = await _load_request(session, request_id, tenant_id, for_update=True)
    if request.status != CONFIG_STATUS_CHANGES_REQUESTED:
        raise ConfigRequestInvalidState(request.status)
    if admin.id != request.maker_admin_id:
        raise ConfigRequestForbidden("Only the original maker may revise this request.")
    # Only a delete carries no payload to edit; create AND update are both
    # revisable (their payload is a full config, editable the same way).
    if request.operation == CONFIG_OP_DELETE:
        raise AppHTTPException(
            422, "config_request_not_editable", "A delete proposal has no payload to revise."
        )

    # A revise is the same trust boundary as propose: re-run BOTH guards propose
    # enforces so a revised payload can't slip past them. `_validate_payload`
    # validates the (possibly multi-band) payload AND asserts every band's
    # tenant matches the request scope (422 config_request_tenant_mismatch).
    normalised, bands = _validate_payload(request.config_type, payload, request.tenant_id)
    if request.operation == CONFIG_OP_UPDATE:
        # Same trust boundary as propose: the revised payload's scope must still
        # match the target the request names, else on approval it would replace a
        # DIFFERENT scope and leave the named config untouched. Reload the target
        # fresh under the request lock. An update always carries a target (propose
        # requires it), so it is non-None here.
        assert request.target_config_id is not None
        await _assert_update_scope_matches_target(
            session,
            request.config_type,
            request.target_config_id,
            request.tenant_id,
            bands[0],
        )
    request.payload = normalised
    request.revision += 1
    _add_review(
        session,
        request,
        actor_admin_id=admin.id,
        actor_role=REVIEW_ROLE_MAKER,
        action=REVIEW_ACTION_REVISED,
    )
    # Snapshot the newly-bumped revision's payload (append-only history).
    _add_revision(session, request)
    _audit(session, admin, request, "config_request.revised", ip_address)
    await record_admin(session, admin)
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
    await record_admin(session, admin)
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
    await record_admin(session, admin)
    await session.commit()
    await session.refresh(request)
    return request


async def list_config_requests(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = None,
    config_type: str | None = None,
) -> list[ConfigChangeRequest]:
    """Return a tenant's config requests, newest-first, optionally by status/type.

    `config_type` lets a native page (Service charges / Commission / …) fetch only
    its own requests (e.g. its CHANGES_REQUESTED items).
    """
    stmt = select(ConfigChangeRequest).where(ConfigChangeRequest.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(ConfigChangeRequest.status == status)
    if config_type is not None:
        stmt = stmt.where(ConfigChangeRequest.config_type == config_type)
    stmt = stmt.order_by(ConfigChangeRequest.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_config_history_for_scope(
    session: AsyncSession,
    tenant_id: UUID,
    config_type: str,
    target_config_id: UUID,
) -> list[ConfigChangeRequest]:
    """Return every APPLIED version of the live config named by target, oldest-first.

    A live config's stable identity is its SCOPE, not its row id — an approved
    `update` atomically replaces the scope, minting a new row id each time. So a
    config's version history is every APPLIED create/update request of this
    config_type whose payload scope equals the live row's scope, in apply order.
    The final entry mirrors the current live values.

    Scope matching handles both payload shapes uniformly: `validate_band_payload`
    parses a multi-band `{"bands": [...]}` (pricing/commission) or a flat dict
    (limit/wallet_limit/tax) into create-schema bands, and `config_scope` reads
    the first band's scope — currency compared case-insensitively.

    Args:
        target_config_id: The CURRENT live row id (an update changes it).

    Returns:
        The matching requests ordered by `updated_at` ASC (apply time — approve
        stages the APPLIED transition in the same commit), so the latest is last.
        Reviews/revisions are omitted to stay lean, mirroring the list endpoint.

    Raises:
        ConfigRequestTargetNotFound (404): no such live row in this tenant.
    """
    target = await load_config_target(session, config_type, target_config_id, tenant_id)
    if target is None:
        raise ConfigRequestTargetNotFound()
    target_scope = config_scope(config_type, target)

    stmt = (
        select(ConfigChangeRequest)
        .where(
            ConfigChangeRequest.tenant_id == tenant_id,
            ConfigChangeRequest.config_type == config_type,
            ConfigChangeRequest.status == CONFIG_STATUS_APPLIED,
            ConfigChangeRequest.operation.in_([CONFIG_OP_CREATE, CONFIG_OP_UPDATE]),
        )
        .order_by(ConfigChangeRequest.updated_at.asc())
    )
    result = await session.execute(stmt)

    history: list[ConfigChangeRequest] = []
    for request in result.scalars().all():
        if not request.payload:
            continue
        bands = validate_band_payload(config_type, request.payload)
        if config_scope(config_type, bands[0]) == target_scope:
            history.append(request)
    return history


async def get_config_request(
    session: AsyncSession, request_id: UUID, tenant_id: UUID
) -> tuple[ConfigChangeRequest, list[ConfigChangeReview], list[ConfigChangeRevision]]:
    """Return a request with its review thread + payload snapshots.

    Returns:
        The request, its review thread (oldest-first), and its per-revision
        payload snapshots (revision-ascending). The list endpoint omits the
        snapshots to stay lean; only this detail path loads them.
    """
    request = await _load_request(session, request_id, tenant_id)
    reviews = await session.execute(
        select(ConfigChangeReview)
        .where(ConfigChangeReview.request_id == request.id)
        .order_by(ConfigChangeReview.created_at.asc())
    )
    revisions = await session.execute(
        select(ConfigChangeRevision)
        .where(ConfigChangeRevision.request_id == request.id)
        .order_by(ConfigChangeRevision.revision.asc())
    )
    return request, list(reviews.scalars().all()), list(revisions.scalars().all())
