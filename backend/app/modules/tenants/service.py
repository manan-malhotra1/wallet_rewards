"""Tenants service — DB-side logic for the tenants admin module.

Read a single tenant by id, patch an existing tenant's editable
identity-card fields (name, business_type), and CREATE a tenant.

Creating a tenant also provisions its baseline catalog — instruments and
services — via `provision_tenant_defaults`. That is the single source of
truth for what a fresh tenant starts with; `scripts/seed.py` calls the same
function so there is exactly one provisioning path (no drift between the
seed and the create-tenant endpoint). Keycloak realm is read-only and not
exposed on either the update or create path.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.modules.audit.service import record_audit_for_admin
from app.modules.tenants.schemas import (
    TenantBrandingUpdate,
    TenantCreate,
    TenantUpdateRequest,
)
from app.shared.exceptions import TenantNameAlreadyExists, TenantNotFound
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Instrument,
    Service,
    Tenant,
)

log = structlog.get_logger(__name__)

# Symbol shown next to amounts for a fiat wallet instrument, keyed by currency
# code. The fallback (used for any code not listed) is the code itself.
_CURRENCY_SYMBOLS = {
    "ZAR": "R",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "KES": "KSh",
    "NGN": "₦",
    "GHS": "GH₵",
    "UGX": "USh",
    "TZS": "TSh",
    "ZMW": "ZK",
    "MWK": "MK",
    "USDT": "₮",
}

# Human display name for a fiat wallet instrument, keyed by currency code. The
# fallback (used for any code not listed) is "{code} wallet currency".
_CURRENCY_DISPLAY_NAMES = {
    "ZAR": "South African Rand",
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "KES": "Kenyan Shilling",
    "NGN": "Nigerian Naira",
    "GHS": "Ghanaian Cedi",
    "UGX": "Ugandan Shilling",
    "TZS": "Tanzanian Shilling",
    "ZMW": "Zambian Kwacha",
    "MWK": "Malawian Kwacha",
    "USDT": "Tether USD",
}

# Baseline services every tenant starts with (code, display_name, description).
# This is the canonical list — `scripts/seed.py` provisions via this module, so
# the seed and the create-tenant endpoint can never diverge.
_BASELINE_SERVICES: list[tuple[str, str, str]] = [
    ("p2p", "Peer-to-Peer", "Send funds from one wallet to another."),
    (
        "airtime_recharge",
        "Airtime Recharge",
        "Recharge a mobile number via a registered airtime merchant.",
    ),
    (
        "redemption",
        "Redemption",
        "Redeem reward points with a registered redemption provider.",
    ),
    ("fund", "Fund", "Admin credits a user's wallet from the operator cash pool."),
    (
        "withdraw",
        "Withdraw",
        "Admin debits a user's wallet and returns funds to the operator cash pool.",
    ),
    (
        "cash_in",
        "Cash In",
        "An agent funds a customer's wallet from the agent's e-float and earns a commission.",
    ),
    (
        "cashout",
        "Cash Out",
        "A subscriber sends money to an agent; the agent earns a commission.",
    ),
    (
        "change_pin",
        "Change PIN",
        "A user changes their own PIN; a charged self-service operation.",
    ),
    (
        "merchant_cashin",
        "Merchant Cash-In",
        "An external partner merchant funds a consumer's wallet via API.",
    ),
]


async def _instrument_exists(session: AsyncSession, tenant_id: uuid.UUID, code: str) -> bool:
    """Return True if a live instrument with this code already exists for the tenant."""
    result = await session.execute(
        select(Instrument.id).where(
            Instrument.tenant_id == tenant_id,
            Instrument.code == code,
            Instrument.deleted_at.is_(None),
        )
    )
    return result.first() is not None


async def _service_exists(session: AsyncSession, tenant_id: uuid.UUID, code: str) -> bool:
    """Return True if a live service with this code already exists for the tenant."""
    result = await session.execute(
        select(Service.id).where(
            Service.tenant_id == tenant_id,
            Service.code == code,
            Service.deleted_at.is_(None),
        )
    )
    return result.first() is not None


async def provision_tenant_defaults(session: AsyncSession, tenant: Tenant) -> None:
    """Idempotently seed a tenant's baseline instruments and services.

    Every tenant needs a starter catalog or the admin UI's currency/service
    dropdowns are empty and no money path can resolve a config. This provisions:

      - A fiat wallet instrument whose `code` is the tenant's OWN
        `base_currency` (e.g. "USD"), with a currency-appropriate symbol and
        display name. This is the bug this function fixes: the code must never
        be hard-coded to ZAR — a USD tenant gets a "USD" instrument, not "ZAR".
      - The "PTS" points instrument (always, regardless of base_currency), since
        the rules engine credits reward points to every tenant.
      - The baseline services (`_BASELINE_SERVICES`).

    Idempotent: a code that already exists (live) is skipped, so re-running is a
    no-op. Mirrors the previous seed behaviour so existing tenants are unaffected.

    Args:
        tenant: The tenant to provision. Must already be persisted (or flushed)
            so `tenant.id` and `tenant.base_currency` are populated.
        session: Async DB session, committed before returning.

    Side effects:
        Inserts Instrument / Service rows for this tenant and commits.
    """
    code = tenant.base_currency.strip().upper()
    symbol = _CURRENCY_SYMBOLS.get(code, code)
    display_name = _CURRENCY_DISPLAY_NAMES.get(code, f"{code} wallet currency")

    if not await _instrument_exists(session, tenant.id, code):
        session.add(
            Instrument(
                tenant_id=tenant.id,
                code=code,
                symbol=symbol,
                display_name=display_name,
                description="Fiat wallet currency.",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            )
        )
    if not await _instrument_exists(session, tenant.id, "PTS"):
        session.add(
            Instrument(
                tenant_id=tenant.id,
                code="PTS",
                symbol="Rewards",
                display_name="Rewards Points",
                description="Loyalty points credited by the rules engine.",
                account_type=ACCOUNT_TYPE_POINTS,
            )
        )

    for svc_code, svc_display, svc_description in _BASELINE_SERVICES:
        if await _service_exists(session, tenant.id, svc_code):
            continue
        session.add(
            Service(
                tenant_id=tenant.id,
                code=svc_code,
                display_name=svc_display,
                description=svc_description,
            )
        )

    await session.commit()
    log.info(
        "tenant_defaults_provisioned",
        tenant_id=str(tenant.id),
        base_currency=code,
    )


async def create_tenant(session: AsyncSession, payload: TenantCreate) -> Tenant:
    """Create a tenant and provision its baseline instruments + services.

    Args:
        session: Async DB session, committed before returning.
        payload: Validated create body (name, business_type, base_currency,
            optional branding).

    Returns:
        The persisted Tenant, provisioned with its baseline catalog.

    Raises:
        TenantNameAlreadyExists: `payload.name` collides with an existing
            tenant (the tenants.name UNIQUE constraint).

    Side effects:
        Inserts the Tenant row plus its baseline Instrument / Service rows,
        committed atomically via `provision_tenant_defaults`.
    """
    tenant = Tenant(
        name=payload.name,
        business_type=payload.business_type,
        base_currency=payload.base_currency,
        brand_accent_color=payload.brand_accent_color,
        brand_light_color=payload.brand_light_color,
        brand_icon_url=payload.brand_icon_url,
    )
    session.add(tenant)
    try:
        # Flush (not commit) so a duplicate name surfaces as a clean 409 BEFORE
        # we start provisioning the catalog. The commit happens inside
        # provision_tenant_defaults once the name is known to be unique.
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if (
            "uq_tenants_name" in str(exc.orig).lower()
            or "tenants_name_key" in str(exc.orig).lower()
        ):
            raise TenantNameAlreadyExists(payload.name) from exc
        raise

    await provision_tenant_defaults(session, tenant)
    await session.refresh(tenant)
    log.info(
        "tenant_created",
        tenant_id=str(tenant.id),
        business_type=tenant.business_type,
        base_currency=tenant.base_currency,
    )
    return tenant


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
