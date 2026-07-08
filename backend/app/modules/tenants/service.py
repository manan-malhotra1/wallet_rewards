"""Tenants service — DB-side logic for the tenants admin module.

Phase 1: read a single tenant by id, and patch an existing tenant's
editable identity-card fields (name, business_type). Keycloak realm is
read-only and not exposed on the update path.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.schemas import TenantUpdateRequest
from app.shared.exceptions import TenantNameAlreadyExists, TenantNotFound
from app.shared.models import Tenant

log = structlog.get_logger(__name__)


async def get_tenant_by_id(tenant_id: uuid.UUID, session: AsyncSession) -> Tenant:
    """Return the tenant or raise TenantNotFound.

    Args:
        tenant_id: Tenant UUID from the URL path.
        session: Async DB session.

    Raises:
        TenantNotFound: tenant_id doesn't map to any active row.
    """
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None or tenant.deleted_at is not None:
        raise TenantNotFound()
    return tenant


async def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdateRequest,
    session: AsyncSession,
) -> Tenant:
    """Apply name / business_type changes to an existing tenant.

    Args:
        tenant_id: Target tenant id.
        payload: TenantUpdateRequest; fields left as None are ignored.
        session: Async DB session, committed before returning.

    Returns:
        The refreshed Tenant row with updated columns.

    Raises:
        TenantNotFound: tenant_id doesn't map to any active row.
        TenantNameAlreadyExists: payload.name collides with another tenant.

    Side effects:
        Commits the session. No Kafka emit (tenants table is configuration,
        not a real-time domain event source).
    """
    tenant = await get_tenant_by_id(tenant_id, session)

    # Snapshot before-state for the structured log. Tenants are configuration,
    # not money — full audit_log integration lands when partner identity changes
    # arrive in Phase 5. For now we log the operator action.
    before = {"name": tenant.name, "business_type": tenant.business_type}

    if payload.name is not None:
        tenant.name = payload.name
    if payload.business_type is not None:
        tenant.business_type = payload.business_type

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # The only UNIQUE on this table is (name), so a name collision can only
        # occur when we actually wrote a new name (payload.name is not None).
        # Guarding both spellings of the constraint name with that check also
        # narrows payload.name to str for the exception constructor.
        if payload.name is not None and (
            "uq_tenants_name" in str(exc.orig).lower()
            or "tenants_name_key" in str(exc.orig).lower()
        ):
            raise TenantNameAlreadyExists(payload.name) from exc
        raise

    await session.refresh(tenant)

    log.info(
        "tenant_updated",
        tenant_id=str(tenant.id),
        before=before,
        after={"name": tenant.name, "business_type": tenant.business_type},
    )
    return tenant
