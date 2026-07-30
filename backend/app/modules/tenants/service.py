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

from app.auth import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.tenants.schemas import TenantBrandingUpdate, TenantUpdateRequest
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
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Tenant:
    """Apply name / business_type changes to an existing tenant.

    Args:
        tenant_id: Target tenant id.
        payload: TenantUpdateRequest; fields left as None are ignored.
        session: Async DB session, committed before returning.
        admin: Authenticated admin — the audit actor.
        ip_address: Caller IP (audit context).

    Returns:
        The refreshed Tenant row with updated columns.

    Raises:
        TenantNotFound: tenant_id doesn't map to any active row.
        TenantNameAlreadyExists: payload.name collides with another tenant.

    Side effects:
        Writes a `tenant.updated` audit_log row (before/after snapshot),
        committed atomically with the change (NFR-0250). No Kafka emit
        (tenants table is configuration, not a real-time domain event source).
    """
    tenant = await get_tenant_by_id(tenant_id, session)

    # Snapshot before-state for both the audit row and the structured log.
    before = {
        "name": tenant.name,
        "business_type": tenant.business_type,
        "base_currency": tenant.base_currency,
        "status": tenant.status,
    }

    if payload.name is not None:
        tenant.name = payload.name
    if payload.business_type is not None:
        tenant.business_type = payload.business_type

    after = {
        "name": tenant.name,
        "business_type": tenant.business_type,
        "base_currency": tenant.base_currency,
        "status": tenant.status,
    }
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant.id,
        action="tenant.updated",
        entity_type="tenant",
        entity_id=str(tenant.id),
        before_state=before,
        after_state=after,
        ip_address=ip_address,
    )

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


async def get_tenant_branding(tenant_id: uuid.UUID, session: AsyncSession) -> Tenant:
    """Return the tenant so the router can read its branding fields.

    Args:
        tenant_id: Tenant UUID from the URL path.
        session: Async DB session.

    Returns:
        The Tenant row (the router serialises its three branding columns).

    Raises:
        TenantNotFound: tenant_id doesn't map to any active row.
    """
    return await get_tenant_by_id(tenant_id, session)


async def update_tenant_branding(
    tenant_id: uuid.UUID,
    payload: TenantBrandingUpdate,
    session: AsyncSession,
) -> Tenant:
    """Set a tenant's cosmetic branding fields in place (upsert-style).

    This is a *direct* edit — branding is purely cosmetic, so it is NOT
    routed through maker-checker and writes no audit trail. The PUT is
    idempotent by construction: it assigns the three fields to exactly the
    values in the payload (a provided value sets it, an explicit `null`
    clears it), so replaying the same body yields the same row.

    Args:
        tenant_id: Target tenant id.
        payload: TenantBrandingUpdate — the desired branding state.
        session: Async DB session, committed before returning.

    Returns:
        The refreshed Tenant row with updated branding columns.

    Raises:
        TenantNotFound: tenant_id doesn't map to any active row.
    """
    tenant = await get_tenant_by_id(tenant_id, session)

    tenant.brand_accent_color = payload.brand_accent_color
    tenant.brand_light_color = payload.brand_light_color
    tenant.brand_icon_url = payload.brand_icon_url

    await session.commit()
    await session.refresh(tenant)

    log.info(
        "tenant_branding_updated",
        tenant_id=str(tenant.id),
        has_accent=tenant.brand_accent_color is not None,
        has_light=tenant.brand_light_color is not None,
        has_icon=tenant.brand_icon_url is not None,
    )
    return tenant
