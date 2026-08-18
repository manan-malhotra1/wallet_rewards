"""Provisioning a new tenant with its baseline instruments and services.

Every tenant must start with a usable catalog: a fiat wallet instrument
keyed to its OWN base_currency (never a hard-coded ZAR), the PTS points
instrument, and the full baseline service set. These tests cover the
`provision_tenant_defaults` / `create_tenant` service functions and the
`POST /api/v1/tenants` endpoint (platform-admin only).
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.schemas import TenantCreate
from app.modules.tenants.service import (
    _BASELINE_SERVICES,
    create_tenant,
    provision_tenant_defaults,
)
from app.shared.models import Instrument, Service, Tenant

_BASELINE_SERVICE_CODES = {code for code, _display, _desc in _BASELINE_SERVICES}


async def _instrument_codes(session: AsyncSession, tenant_id) -> set[str]:
    """Return the set of live instrument codes for a tenant."""
    result = await session.execute(
        select(Instrument.code).where(
            Instrument.tenant_id == tenant_id, Instrument.deleted_at.is_(None)
        )
    )
    return set(result.scalars().all())


async def _service_codes(session: AsyncSession, tenant_id) -> set[str]:
    """Return the set of live service codes for a tenant."""
    result = await session.execute(
        select(Service.code).where(Service.tenant_id == tenant_id, Service.deleted_at.is_(None))
    )
    return set(result.scalars().all())


# -----------------------------------------------------------------------------
# Service-level provisioning
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tenant_provisions_all_baseline_services(
    db_session: AsyncSession,
) -> None:
    """Verify a newly-created tenant can use every baseline service out of the box"""
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"svc-tenant-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="USD",
        ),
    )
    assert await _service_codes(db_session, tenant.id) == _BASELINE_SERVICE_CODES


@pytest.mark.asyncio
async def test_new_tenant_wallet_instrument_uses_own_currency_not_zar(
    db_session: AsyncSession,
) -> None:
    """Verify a USD tenant's wallet is denominated in USD, never a hard-coded ZAR"""
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"usd-tenant-{uuid4().hex[:8]}",
            business_type="wallet",
            base_currency="USD",
        ),
    )
    codes = await _instrument_codes(db_session, tenant.id)
    assert "USD" in codes
    assert "ZAR" not in codes

    # The USD instrument carries the right symbol + display name.
    usd = (
        await db_session.execute(
            select(Instrument).where(Instrument.tenant_id == tenant.id, Instrument.code == "USD")
        )
    ).scalar_one()
    assert usd.symbol == "$"
    assert usd.display_name == "US Dollar"
    assert usd.account_type == "financial_wallet"


@pytest.mark.asyncio
async def test_new_tenant_gets_points_instrument(db_session: AsyncSession) -> None:
    """Verify every new tenant can earn reward points via a PTS instrument"""
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"pts-tenant-{uuid4().hex[:8]}",
            business_type="rewards",
            base_currency="KES",
        ),
    )
    pts = (
        await db_session.execute(
            select(Instrument).where(Instrument.tenant_id == tenant.id, Instrument.code == "PTS")
        )
    ).scalar_one()
    assert pts.account_type == "points_account"


@pytest.mark.asyncio
async def test_provisioning_is_idempotent(db_session: AsyncSession) -> None:
    """Verify re-provisioning a tenant never duplicates its instruments or services"""
    tenant = Tenant(
        name=f"idem-tenant-{uuid4().hex[:8]}",
        business_type="both",
        base_currency="USD",
    )
    db_session.add(tenant)
    await db_session.commit()

    await provision_tenant_defaults(db_session, tenant)
    await provision_tenant_defaults(db_session, tenant)

    instruments = (
        (await db_session.execute(select(Instrument).where(Instrument.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    services = (
        (await db_session.execute(select(Service).where(Service.tenant_id == tenant.id)))
        .scalars()
        .all()
    )

    assert len(instruments) == 2  # exactly USD + PTS, not four
    assert len(services) == len(_BASELINE_SERVICES)


@pytest.mark.asyncio
async def test_tenant_catalog_is_isolated_per_tenant(db_session: AsyncSession) -> None:
    """Verify one tenant's instruments and services are never visible to another"""
    usd_tenant = await create_tenant(
        db_session,
        TenantCreate(name=f"iso-usd-{uuid4().hex[:8]}", business_type="both", base_currency="USD"),
    )
    eur_tenant = await create_tenant(
        db_session,
        TenantCreate(name=f"iso-eur-{uuid4().hex[:8]}", business_type="both", base_currency="EUR"),
    )

    usd_codes = await _instrument_codes(db_session, usd_tenant.id)
    eur_codes = await _instrument_codes(db_session, eur_tenant.id)
    assert "USD" in usd_codes and "EUR" not in usd_codes
    assert "EUR" in eur_codes and "USD" not in eur_codes

    # Services are scoped per tenant, never shared.
    usd_svc = (
        (await db_session.execute(select(Service).where(Service.tenant_id == usd_tenant.id)))
        .scalars()
        .all()
    )
    assert {s.tenant_id for s in usd_svc} == {usd_tenant.id}


# -----------------------------------------------------------------------------
# POST /api/v1/tenants
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_tenant_happy_path_returns_201_and_provisions(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Verify a platform admin can create a tenant and it comes pre-provisioned"""
    name = f"api-tenant-{uuid4().hex[:8]}"
    resp = await async_client.post(
        "/api/v1/tenants",
        headers=admin_auth_header,
        json={"name": name, "business_type": "both", "base_currency": "USD"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == name
    assert body["base_currency"] == "USD"

    tenant_id = body["id"]
    assert "USD" in await _instrument_codes(db_session, tenant_id)
    assert await _service_codes(db_session, tenant_id) == _BASELINE_SERVICE_CODES


@pytest.mark.asyncio
async def test_post_tenant_requires_auth(async_client: AsyncClient) -> None:
    """Verify a signed-out user cannot create a tenant"""
    resp = await async_client.post(
        "/api/v1/tenants",
        json={"name": "anon-co", "business_type": "both", "base_currency": "USD"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_tenant_wrong_role_forbidden(
    async_client: AsyncClient,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify an admin without the platform-admin role cannot create a tenant"""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "nope-co", "business_type": "both", "base_currency": "USD"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_tenant_rejects_unknown_business_type(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a tenant cannot be created with an unsupported business type"""
    resp = await async_client.post(
        "/api/v1/tenants",
        headers=admin_auth_header,
        json={"name": "bad-bt-co", "business_type": "loyalty", "base_currency": "USD"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_tenant_rejects_bad_currency(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a tenant cannot be created with an out-of-range currency code"""
    resp = await async_client.post(
        "/api/v1/tenants",
        headers=admin_auth_header,
        json={"name": "bad-cur-co", "business_type": "both", "base_currency": "US"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_tenant_duplicate_name_returns_409(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify two tenants cannot be created with the same name"""
    name = f"dup-tenant-{uuid4().hex[:8]}"
    body = {"name": name, "business_type": "both", "base_currency": "USD"}

    first = await async_client.post("/api/v1/tenants", headers=admin_auth_header, json=body)
    assert first.status_code == 201, first.text

    second = await async_client.post("/api/v1/tenants", headers=admin_auth_header, json=body)
    assert second.status_code == 409
    assert second.json()["error_code"] == "tenant_name_already_exists"


# -----------------------------------------------------------------------------
# System-wallet provisioning (story B5.1)
# -----------------------------------------------------------------------------


async def _system_accounts(session: AsyncSession, tenant_id) -> dict[str, str]:
    """Return {account_type: currency} for a tenant's system-owned accounts."""
    from app.shared.models import Account

    result = await session.execute(
        select(Account.account_type, Account.currency).where(
            Account.tenant_id == tenant_id, Account.user_id.is_(None)
        )
    )
    return dict(result.all())


@pytest.mark.asyncio
async def test_new_tenant_system_wallets_use_own_currency_not_zar(
    db_session: AsyncSession,
) -> None:
    """Verify a USD tenant's system wallets are USD, never a hard-coded ZAR.

    The regression that matters most: this script's predecessor (seed.py)
    hard-coded these to ZAR, the same bug class once fixed for instruments.
    """
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"sysw-usd-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="USD",
        ),
    )
    accounts = await _system_accounts(db_session, tenant.id)

    assert accounts["system_cash_inflow"] == "USD"
    assert accounts["system_fee_collected"] == "USD"
    assert accounts["commission"] == "USD"
    assert accounts["tax_service_collected"] == "USD"
    assert accounts["tax_commission_collected"] == "USD"
    # The points issuance pool is always PTS, regardless of base currency.
    assert accounts["system_points_issuance"] == "PTS"
    assert "ZAR" not in accounts.values()


@pytest.mark.asyncio
async def test_no_bank_mirror_is_provisioned(db_session: AsyncSession) -> None:
    """Verify provisioning never creates an operator_adjustment account.

    A bank mirror represents a real bank account, so the operator must create
    it explicitly with its real details — a defaulted mirror row would invite
    posting against an account that does not actually exist at the bank.
    """
    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"sysw-mirror-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="ZAR",
        ),
    )
    accounts = await _system_accounts(db_session, tenant.id)

    assert "operator_adjustment" not in accounts


@pytest.mark.asyncio
async def test_system_wallet_provisioning_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """Verify re-provisioning creates no duplicate system accounts."""
    from app.shared.models import Account

    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"sysw-idem-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="ZAR",
        ),
    )
    await provision_tenant_defaults(db_session, tenant)

    result = await db_session.execute(
        select(Account.account_type).where(
            Account.tenant_id == tenant.id, Account.user_id.is_(None)
        )
    )
    types = list(result.scalars().all())
    assert len(types) == len(set(types))


@pytest.mark.asyncio
async def test_fresh_tenant_float_can_be_prefunded_without_a_prior_transaction(
    db_session: AsyncSession,
) -> None:
    """Verify the provisioning deadlock is gone (story B5.1).

    Before this fix the float only existed after a fund() had been attempted,
    but invariant #11 requires the float to be pre-funded BEFORE it can fund
    anyone — so the operator's only route was to trigger a fund that FAILS.
    Now `adjust_system_wallet` can target the float straight after tenant
    creation, with no transaction ever attempted.
    """
    from decimal import Decimal

    from app.auth import AdminPrincipal
    from app.modules.treasury.service import adjust_system_wallet
    from app.shared.models import ACCOUNT_TYPE_OPERATOR_ADJUSTMENT, Account

    tenant = await create_tenant(
        db_session,
        TenantCreate(
            name=f"sysw-fund-{uuid4().hex[:8]}",
            business_type="both",
            base_currency="USD",
        ),
    )
    float_account = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == "system_cash_inflow",
            )
        )
    ).scalar_one()
    # The mirror is the one account an operator creates explicitly (it carries
    # real bank details), so the test creates it the way the UI would.
    mirror = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency="USD",
        name="Primary",
    )
    db_session.add(mirror)
    await db_session.commit()
    await db_session.refresh(mirror)

    response = await adjust_system_wallet(
        db_session,
        tenant_id=tenant.id,
        account_id=float_account.id,
        amount=Decimal("1000"),
        bank_mirror_account_id=mirror.id,
        reason="initial float funding",
        admin=AdminPrincipal(
            id="00000000-0000-4000-8000-0000000000ad",
            username="admin",
            roles=frozenset(),
        ),
    )
    assert response.new_balance == Decimal("1000")


@pytest.mark.asyncio
async def test_system_wallets_are_isolated_per_tenant(
    db_session: AsyncSession,
) -> None:
    """Verify each tenant's system accounts belong to it alone."""
    first = await create_tenant(
        db_session,
        TenantCreate(name=f"sysw-a-{uuid4().hex[:8]}", business_type="both", base_currency="USD"),
    )
    second = await create_tenant(
        db_session,
        TenantCreate(name=f"sysw-b-{uuid4().hex[:8]}", business_type="both", base_currency="KES"),
    )

    assert (await _system_accounts(db_session, first.id))["system_cash_inflow"] == "USD"
    assert (await _system_accounts(db_session, second.id))["system_cash_inflow"] == "KES"


@pytest.mark.asyncio
async def test_updating_a_tenant_tops_up_missing_provisioning(
    db_session: AsyncSession,
) -> None:
    """Verify re-saving a tenant provisions anything it is missing.

    This is the operator-reachable remedy the System wallets empty state points
    at: a tenant created before a provisioning gap was fixed gets its missing
    pieces on the next save, without any script.
    """
    from app.auth import AdminPrincipal
    from app.modules.tenants.schemas import TenantUpdateRequest
    from app.modules.tenants.service import update_tenant

    # A tenant persisted WITHOUT provisioning — as every tenant created before
    # B5.1 shipped was.
    tenant = Tenant(name=f"legacy-{uuid4().hex[:8]}", business_type="both", base_currency="USD")
    db_session.add(tenant)
    await db_session.commit()
    assert await _system_accounts(db_session, tenant.id) == {}

    await update_tenant(
        tenant.id,
        TenantUpdateRequest(name=None, business_type=None),
        db_session,
        admin=AdminPrincipal(
            id="00000000-0000-4000-8000-0000000000ad",
            username="admin",
            roles=frozenset(),
        ),
    )

    accounts = await _system_accounts(db_session, tenant.id)
    assert accounts["system_cash_inflow"] == "USD"
    assert accounts["system_points_issuance"] == "PTS"
