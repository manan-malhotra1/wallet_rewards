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
            f"Base service '{payload.base_service_code}' is not provisioned for "
            "this tenant.",
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
