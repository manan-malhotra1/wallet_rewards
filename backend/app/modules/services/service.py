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
from app.shared.exceptions import ServiceCodeAlreadyExists, ServiceNotFound
from app.shared.models import Service

log = structlog.get_logger(__name__)


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
    """Insert a new catalog row.

    Args:
        session: Async DB session.
        payload: Validated create request.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP (audit context).

    Raises:
        ServiceCodeAlreadyExists: another live row with the same code exists.

    Side effects:
        Writes a `service.created` audit_log row, committed atomically with the
        insert (NFR-0250).
    """
    service = Service(
        tenant_id=payload.tenant_id,
        code=payload.code,
        display_name=payload.display_name,
        description=payload.description,
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
    }

    if payload.display_name is not None:
        service.display_name = payload.display_name
    if payload.description is not None:
        service.description = payload.description
    if payload.status is not None:
        service.status = payload.status

    record_audit_for_admin(
        session,
        admin,
        tenant_id=service.tenant_id,
        action="service.updated",
        entity_type="service",
        entity_id=str(service.id),
        before_state=before,
        after_state={"display_name": service.display_name, "status": service.status},
        ip_address=ip_address,
    )
    await session.commit()
    await session.refresh(service)
    log.info(
        "service_updated",
        tenant_id=str(service.tenant_id),
        service_id=str(service.id),
        before=before,
        after={"display_name": service.display_name, "status": service.status},
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

    Side effects:
        Writes a `service.deleted` audit_log row (before-state snapshot),
        committed atomically with the soft-delete (NFR-0250).
    """
    service = await get_service_by_id(session, tenant_id, service_id)
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
