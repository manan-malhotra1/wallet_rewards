"""Services catalog service-layer logic.

Owns the CRUD over the `services` table. The catalog backs the dropdowns
in Limits / Pricing / Campaigns admin pages and replaces what used to be
a free-text transaction_type field.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.services.schemas import (
    ServiceCreateRequest,
    ServiceUpdateRequest,
)
from app.shared.exceptions import (
    AppHTTPException,
    ServiceCodeAlreadyExists,
    ServiceNotAllowedForUserType,
    ServiceNotAllowedOnChannel,
    ServiceNotFound,
)
from app.shared.models import SERVICE_STATUS_ACTIVE, Service
from app.shared.services_registry import BASE_SERVICE_CODES, DERIVABLE_BASE_CODES

log = structlog.get_logger(__name__)


def _is_narrower_or_equal(derived: list[str] | None, base: list[str] | None) -> bool:
    """Return whether a derived allow-list never grants what the base excludes.

    Implements the "narrowing-only" rule of spec §6.2: NULL/empty on the base
    means "unrestricted on this dimension" and contributes no restriction, so
    any derived value is fine. NULL/empty on the derived side means "no
    restriction requested", which is only valid when the base is itself
    unrestricted — otherwise the derived service would be wider than its base.

    Args:
        derived: The candidate service's allow-list for one dimension.
        base: The base service's allow-list for the same dimension.

    Returns:
        True if `derived` is a subset of `base` (or `base` is unrestricted).
    """
    if not base:
        return True
    if not derived:
        return False
    return set(derived) <= set(base)


async def _assert_valid_derived_payload(
    session: AsyncSession, payload: ServiceCreateRequest
) -> None:
    """Reject a derived-service create that could never work.

    Four failure modes, each of which would otherwise produce config that
    silently never executes or resolves permissions incorrectly (spec §6,
    §6.2):
      - the new code shadows a platform code, which would make the derived
        row ambiguous with the base flow itself;
      - the named base isn't derivable (non-financial, or not implemented);
      - the base isn't provisioned live in this tenant;
      - the derived access policy allows a user type or channel its base
        excludes (checked at save time; resolution also enforces the
        intersection as belt-and-braces — see `resolve_service_code`).

    Args:
        session: Async DB session (read-only here).
        payload: The validated create request.

    Raises:
        AppHTTPException: 422 `service_code_reserved`, `invalid_base_service`,
            or `policy_wider_than_base`.
    """
    if payload.code in BASE_SERVICE_CODES:
        raise AppHTTPException(
            422,
            "service_code_reserved",
            f"'{payload.code}' is a platform service code and cannot be reused.",
        )
    if payload.base_service_code not in DERIVABLE_BASE_CODES:
        raise AppHTTPException(
            422,
            "invalid_base_service",
            f"'{payload.base_service_code}' is not a derivable platform service. "
            f"Derivable: {', '.join(sorted(DERIVABLE_BASE_CODES))}.",
        )
    base = (
        await session.execute(
            select(Service).where(
                Service.tenant_id == payload.tenant_id,
                Service.code == payload.base_service_code,
                Service.kind == "base",
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if base is None:
        raise AppHTTPException(
            422,
            "invalid_base_service",
            f"Base service '{payload.base_service_code}' is not provisioned for this tenant.",
        )
    if not _is_narrower_or_equal(
        payload.allowed_user_types, base.allowed_user_types
    ) or not _is_narrower_or_equal(payload.allowed_channels, base.allowed_channels):
        raise AppHTTPException(
            422,
            "policy_wider_than_base",
            "This service's access policy cannot allow a user type or channel "
            "that its base service excludes.",
        )


def _intersect_allow_lists(derived: list[str] | None, base: list[str] | None) -> list[str] | None:
    """Return the enforceable allow-list for one policy dimension.

    Companion to `_is_narrower_or_equal` (which only answers "is this valid
    to save"): this computes the actual effective set to enforce AT
    RESOLUTION TIME. NULL/empty on either side means "unrestricted on this
    dimension" (spec §6.2) and contributes no restriction; when both sides
    restrict, the effective set is their intersection — belt-and-braces so a
    base narrowed AFTER a derived service was saved still tightens it.

    Args:
        derived: The derived service's allow-list for one dimension.
        base: The base service's CURRENT allow-list for the same dimension.

    Returns:
        None/empty when unrestricted on this dimension; otherwise the
        intersected allow-list.
    """
    if not base:
        return derived
    if not derived:
        return base
    return [value for value in derived if value in base]


async def resolve_service_code(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    base_code: str,
    requested_code: str | None,
    user_type: str | None = None,
    channel: str | None = None,
) -> str:
    """Resolve the service code a money flow should transact under.

    Every money endpoint calls this exactly once, before any ledger work, so
    all flows behave identically (spec §7). The returned code drives
    permission, pricing, limits and the recorded `transaction_type`; the
    caller passes `base_code` as `base_transaction_type` regardless.

    When `user_type` and/or `channel` are supplied and the resolved code is a
    derived service, also enforces the resolution-time narrowing rule (spec
    §6.2): the effective policy is the INTERSECTION of the base's CURRENT
    allow-lists and the derived row's own, not just the derived row's own
    snapshot from save time. This is belt-and-braces on top of the
    save-time-only check in `_assert_valid_derived_payload` — if a base is
    later narrowed, every derived service tightens with it automatically
    instead of silently outliving the restriction. Reuses the same
    `ServiceNotAllowedForUserType` / `ServiceNotAllowedOnChannel` errors
    `assert_service_allowed` raises, so callers handle one pair of exception
    types regardless of which check caught the denial.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope.
        base_code: The endpoint's own platform code, e.g. 'p2p'.
        requested_code: The client-supplied `service_code`, or None.
        user_type: The acting user's type, for the WHO intersection check.
            None skips the WHO dimension (matches `assert_service_allowed`).
        channel: The initiating channel, for the HOW intersection check.
            None skips the HOW dimension.

    Returns:
        `base_code` when nothing was requested, or an explicit request for
        the base itself; otherwise the resolved derived code.

    Raises:
        ServiceNotFound: 404 — no live row for `(tenant_id, requested_code)`.
        AppHTTPException: 409 `service_disabled`; 422 `service_code_mismatch`
            when the code is unrelated to `base_code`.
        ServiceNotAllowedForUserType: 403 — resolution-time WHO intersection.
        ServiceNotAllowedOnChannel: 403 — resolution-time HOW intersection.
    """
    if requested_code is None or requested_code == base_code:
        return base_code

    row = (
        await session.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.code == requested_code,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ServiceNotFound()
    if row.status != SERVICE_STATUS_ACTIVE:
        raise AppHTTPException(409, "service_disabled", f"Service '{requested_code}' is disabled.")
    # A derived service may only be invoked through its own base's endpoint —
    # otherwise a cash-out derivative could be driven by the P2P flow.
    if row.kind != "derived" or row.base_service_code != base_code:
        raise AppHTTPException(
            422,
            "service_code_mismatch",
            f"Service '{requested_code}' cannot be used for '{base_code}'.",
        )

    if user_type is not None or channel is not None:
        base_row = (
            await session.execute(
                select(Service).where(
                    Service.tenant_id == tenant_id,
                    Service.code == base_code,
                    Service.kind == "base",
                    Service.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        # No live base row is a pre-existing dead-config state the registry
        # guard should have already prevented; nothing to intersect against.
        if base_row is not None:
            effective_user_types = _intersect_allow_lists(
                row.allowed_user_types, base_row.allowed_user_types
            )
            effective_channels = _intersect_allow_lists(
                row.allowed_channels, base_row.allowed_channels
            )
            if (
                user_type is not None
                and effective_user_types
                and user_type not in effective_user_types
            ):
                raise ServiceNotAllowedForUserType()
            if channel is not None and effective_channels and channel not in effective_channels:
                raise ServiceNotAllowedOnChannel()

    return requested_code


async def assert_service_allowed(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    transaction_type: str,
    user_type: str | None,
    channel: str,
) -> None:
    """Enforce the tenant's per-service access policy for a money path.

    This is the server-side twin of the mobile `/me/services` display query: it
    makes what the API ALLOWS match what the app DISPLAYS. The live `Service`
    row for `transaction_type` carries two allow-lists — `allowed_user_types`
    (WHO) and `allowed_channels` (HOW) — and both must permit the caller.

    Semantics (identical to `identity.list_my_services`): for EACH dimension a
    NULL or empty array means "unrestricted" (all values allowed); a non-empty
    array is an allow-list. The two dimensions are ANDed. An empty/None array is
    detected here with plain truthiness (`not arr`), the Python equivalent of the
    query's `array_length(col, 1) IS NULL`.

    An **unconfigured** service (no active, non-deleted `Service` row for the
    code) imposes NO restriction — the request keeps working. This matches the
    NULL=all philosophy: absence of policy is not a restriction.

    A `user_type` of ``None`` SKIPS the WHO dimension entirely and enforces only
    the channel (HOW) dimension. This is used by operator/API money paths (e.g.
    `fund` / `withdraw`) where there is no single acting wallet-user type — the
    channel gate alone confines the operation.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — services never resolve across tenants.
        transaction_type: The service code being initiated (== `Service.code`).
        user_type: The acting user's type, or ``None`` to skip the WHO check.
        channel: The initiating channel (e.g. "mobile", "api").

    Raises:
        ServiceNotAllowedForUserType (403): `user_type` is not on a non-empty
            `allowed_user_types` list.
        ServiceNotAllowedOnChannel (403): `channel` is not on a non-empty
            `allowed_channels` list.
    """
    service = (
        await session.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.code == transaction_type,
                Service.status == SERVICE_STATUS_ACTIVE,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    # No policy row = unconfigured service = unrestricted (NULL=all philosophy).
    if service is None:
        return

    # WHO dimension — skipped when user_type is None (channel-only enforcement).
    if (
        user_type is not None
        and service.allowed_user_types
        and user_type not in service.allowed_user_types
    ):
        raise ServiceNotAllowedForUserType()

    # HOW dimension — NULL/empty = unrestricted.
    if service.allowed_channels and channel not in service.allowed_channels:
        raise ServiceNotAllowedOnChannel()


async def list_services(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    status: str | None = None,
) -> list[Service]:
    """Return non-deleted services for the tenant.

    Args:
        tenant_id: Filter by this tenant.
        status: Optional 'active' / 'disabled' filter; None returns both.

    Returns:
        List of Service rows, newest first.
    """
    stmt = (
        select(Service)
        .where(Service.tenant_id == tenant_id, Service.deleted_at.is_(None))
        .order_by(Service.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Service.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_service_by_id(
    session: AsyncSession, tenant_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    """Return one service or raise ServiceNotFound.

    Raises:
        ServiceNotFound: id missing in this tenant or soft-deleted.
    """
    stmt = select(Service).where(
        Service.id == service_id,
        Service.tenant_id == tenant_id,
        Service.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    service = result.scalar_one_or_none()
    if service is None:
        raise ServiceNotFound()
    return service


async def create_service(
    session: AsyncSession,
    payload: ServiceCreateRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Service:
    """Insert a new derived-service catalog row.

    Only derived services can be created here (spec §6) — base services ship
    with the platform and are provisioned per tenant elsewhere. `kind` is
    always 'derived'; `_assert_valid_derived_payload` has already confirmed
    the base is derivable, live in this tenant, and that the new code doesn't
    shadow a platform code or widen the base's access policy.

    Args:
        session: Async DB session.
        payload: Validated create request.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP (audit context).

    Raises:
        AppHTTPException: 422 `service_code_reserved`, `invalid_base_service`,
            or `policy_wider_than_base` (from `_assert_valid_derived_payload`).
        ServiceCodeAlreadyExists: another live row with the same code exists.

    Side effects:
        Writes a `service.created` audit_log row, committed atomically with the
        insert (NFR-0250).
    """
    await _assert_valid_derived_payload(session, payload)
    service = Service(
        tenant_id=payload.tenant_id,
        code=payload.code,
        display_name=payload.display_name,
        description=payload.description,
        kind="derived",
        base_service_code=payload.base_service_code,
        # NULL/omitted stays unrestricted; an empty list persists as-is.
        allowed_user_types=payload.allowed_user_types,
        allowed_channels=payload.allowed_channels,
    )
    session.add(service)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_services_tenant_code_alive" in str(exc.orig).lower():
            raise ServiceCodeAlreadyExists(payload.code) from exc
        raise
    record_audit_for_admin(
        session,
        admin,
        tenant_id=service.tenant_id,
        action="service.created",
        entity_type="service",
        entity_id=str(service.id),
        after_state={
            "code": service.code,
            "display_name": service.display_name,
            "status": service.status,
            "kind": service.kind,
            "base_service_code": service.base_service_code,
            "allowed_user_types": service.allowed_user_types,
            "allowed_channels": service.allowed_channels,
        },
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(service)
    log.info(
        "service_created",
        tenant_id=str(service.tenant_id),
        service_id=str(service.id),
        code=service.code,
    )
    return service


async def update_service(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    service_id: uuid.UUID,
    payload: ServiceUpdateRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Service:
    """Apply display_name / description / status edits.

    Code is intentionally immutable here — see schemas.ServiceUpdateRequest.

    Side effects:
        Writes a `service.updated` audit_log row (before/after snapshot),
        committed atomically with the change (NFR-0250).
    """
    service = await get_service_by_id(session, tenant_id, service_id)
    before = {
        "display_name": service.display_name,
        "status": service.status,
        "allowed_user_types": service.allowed_user_types,
        "allowed_channels": service.allowed_channels,
    }

    if payload.display_name is not None:
        service.display_name = payload.display_name
    if payload.description is not None:
        service.description = payload.description
    if payload.status is not None:
        service.status = payload.status
    # `None` = leave the policy untouched (partial edit must not wipe it); an
    # explicit `[]` is a real value and IS persisted (restrict-to-none).
    if payload.allowed_user_types is not None:
        service.allowed_user_types = payload.allowed_user_types
    if payload.allowed_channels is not None:
        service.allowed_channels = payload.allowed_channels

    after = {
        "display_name": service.display_name,
        "status": service.status,
        "allowed_user_types": service.allowed_user_types,
        "allowed_channels": service.allowed_channels,
    }
    record_audit_for_admin(
        session,
        admin,
        tenant_id=service.tenant_id,
        action="service.updated",
        entity_type="service",
        entity_id=str(service.id),
        before_state=before,
        after_state=after,
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(service)
    log.info(
        "service_updated",
        tenant_id=str(service.tenant_id),
        service_id=str(service.id),
        before=before,
        after=after,
    )
    return service


async def soft_delete_service(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    service_id: uuid.UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Service:
    """Mark the service as deleted_at=now() and return the row.

    Idempotent: deleting an already-deleted service raises ServiceNotFound
    (callers should treat that as a 404 rather than a 409, mirroring the
    way `get_service_by_id` handles soft-deleted rows).

    Raises:
        AppHTTPException: 409 `base_service_protected` — base services ship
            with the platform and are undeletable (spec §6). Editing a base's
            status/display_name/policy stays allowed; only deletion is
            blocked, so `update_service` does NOT carry this guard.

    Side effects:
        Writes a `service.deleted` audit_log row (before-state snapshot),
        committed atomically with the soft-delete (NFR-0250).
    """
    service = await get_service_by_id(session, tenant_id, service_id)
    if service.kind == "base":
        raise AppHTTPException(
            409,
            "base_service_protected",
            "Base services ship with the platform and cannot be deleted.",
        )
    before = {
        "code": service.code,
        "display_name": service.display_name,
        "status": service.status,
    }
    service.deleted_at = datetime.now(UTC)
    record_audit_for_admin(
        session,
        admin,
        tenant_id=service.tenant_id,
        action="service.deleted",
        entity_type="service",
        entity_id=str(service.id),
        before_state=before,
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(service)
    log.info(
        "service_deleted",
        tenant_id=str(service.tenant_id),
        service_id=str(service.id),
        code=service.code,
    )
    return service
