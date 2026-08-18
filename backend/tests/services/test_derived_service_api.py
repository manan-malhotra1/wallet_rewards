"""Derived-service creation via the admin catalog API (spec §6).

Only derived services can be created here: base services ship with the
platform. These tests pin the rejection paths, because each one is a way an
operator could otherwise create config that silently never works: an
unresolvable base, a code that shadows a platform flow, a base from another
tenant, or an access policy wider than its base (spec §6.2).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Service, Tenant


async def _seed_base(
    session: AsyncSession,
    tenant: Tenant,
    code: str,
    *,
    allowed_user_types: list[str] | None = None,
    allowed_channels: list[str] | None = None,
) -> Service:
    """Persist an active base service the way provision_tenant_defaults does."""
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code.replace("_", " ").title(),
        kind="base",
        status="active",
        allowed_user_types=allowed_user_types,
        allowed_channels=allowed_channels,
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_admin_can_create_a_derived_service(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a derived service is created against a live base"""
    await _seed_base(db_session, test_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "derived"
    assert body["base_service_code"] == "cashout"


@pytest.mark.asyncio
async def test_create_requires_a_base_service_code(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify omitting the base is refused — base services aren't created here"""
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "school_fees",
            "display_name": "School Fees",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_rejects_a_non_derivable_base(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify change_pin cannot be derived — no fee or limit to differentiate"""
    await _seed_base(db_session, test_tenant, "change_pin")

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "change_pin_fast",
            "display_name": "Fast PIN change",
            "base_service_code": "change_pin",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_base_service"


@pytest.mark.asyncio
async def test_create_rejects_a_base_absent_from_the_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify deriving from a base this tenant doesn't have is refused"""
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_base_service"


@pytest.mark.asyncio
async def test_create_rejects_a_code_that_shadows_a_platform_code(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a derived service cannot take an implemented platform code"""
    await _seed_base(db_session, test_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "p2p",
            "display_name": "Sneaky P2P",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_code_reserved"


@pytest.mark.asyncio
async def test_derived_service_is_tenant_isolated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a base in another tenant cannot satisfy this tenant's derive"""
    await _seed_base(db_session, other_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_base_service"


@pytest.mark.asyncio
async def test_create_rejects_a_policy_wider_than_the_base(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a derived policy cannot name a channel its base excludes (spec §6.2)

    The base restricts to ['web', 'mobile']; the derived service asks for
    'ussd' too, which the base doesn't allow. This must be rejected at save
    time rather than silently accepted and only enforced at resolution.
    """
    await _seed_base(
        db_session,
        test_tenant,
        "cashout",
        allowed_channels=["web", "mobile"],
    )

    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
            "allowed_channels": ["mobile", "ussd"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "policy_wider_than_base"


async def test_list_marks_which_bases_are_derivable(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify GET exposes `derivable` so the admin UI needn't copy the registry.

    Three rows, three answers: a derivable base (`p2p`) is true; the
    non-derivable base `change_pin` is false even though it IS a base; and a
    derived row is false because you cannot derive from a derivation. Without
    this field the UI would have to hardcode DERIVABLE_BASE_CODES in
    TypeScript, and adding a non-derivable base later would silently leave it
    offered in the base dropdown until someone edited the copy.
    """
    await _seed_base(db_session, test_tenant, "p2p")
    await _seed_base(db_session, test_tenant, "change_pin")
    db_session.add(
        Service(
            tenant_id=test_tenant.id,
            code="p2p_diaspora",
            display_name="Diaspora Transfer",
            kind="derived",
            base_service_code="p2p",
            status="active",
        )
    )
    await db_session.commit()

    resp = await async_client.get(
        f"/api/v1/services?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    derivable = {row["code"]: row["derivable"] for row in resp.json()}

    assert derivable["p2p"] is True
    assert derivable["change_pin"] is False
    assert derivable["p2p_diaspora"] is False


async def test_list_reports_which_prerequisites_a_service_is_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify readiness names the missing piece instead of leaving a 422 to find.

    A service row alone moves no money: it also needs a pricing config, a limit
    config, and an ACTIVE role granting its code. This is the whole point of the
    signal — a freshly created derived service reports all three false, so the
    admin sees what is missing rather than discovering it one failed
    transaction at a time.
    """
    from decimal import Decimal

    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, LimitConfig, PricingConfig

    await _seed_base(db_session, test_tenant, "p2p")
    db_session.add(
        Service(
            tenant_id=test_tenant.id,
            code="p2p_diaspora",
            display_name="Diaspora Transfer",
            kind="derived",
            base_service_code="p2p",
            status="active",
        )
    )
    # The base gets pricing + limits but NO role grant; the derived service gets
    # nothing. Two rows, two different partial states.
    db_session.add(
        PricingConfig(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        )
    )
    db_session.add(
        LimitConfig(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            min_amount=Decimal("1"),
            max_amount=Decimal("1000"),
        )
    )
    await db_session.commit()

    resp = await async_client.get(
        f"/api/v1/services?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    readiness = {row["code"]: row["readiness"] for row in resp.json()}

    assert readiness["p2p"] == {"pricing": True, "limits": True, "role": False}
    assert readiness["p2p_diaspora"] == {
        "pricing": False,
        "limits": False,
        "role": False,
    }


async def test_readiness_does_not_demand_a_role_for_flows_that_ignore_roles(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify only role-enforced flows report the role prerequisite.

    `fund` / `withdraw` are admin-initiated, `merchant_cashin` authenticates a
    partner by API key, and `change_pin` is not role-gated — none of them call
    `require_permission`, so telling an operator they "need a role grant" sends
    them to fix something that would change nothing.
    """
    for code in ("fund", "withdraw", "merchant_cashin", "change_pin", "p2p"):
        await _seed_base(db_session, test_tenant, code)

    resp = await async_client.get(
        f"/api/v1/services?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    role_ready = {row["code"]: row["readiness"]["role"] for row in resp.json()}

    assert role_ready["fund"] is True
    assert role_ready["withdraw"] is True
    assert role_ready["merchant_cashin"] is True
    assert role_ready["change_pin"] is True
    # p2p DOES enforce roles, and nothing granted it here.
    assert role_ready["p2p"] is False


async def test_readiness_counts_a_derived_service_as_ready_via_its_base(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the badge agrees with `has_permission` about inheritance.

    A derived service inherits its base's role grants (B4.6). If readiness
    ignored that it would report "needs role grant" for a variant the money
    path happily permits — the screen contradicting the code.
    """
    from app.shared.models import Role, RolePermission

    await _seed_base(db_session, test_tenant, "p2p")
    db_session.add(
        Service(
            tenant_id=test_tenant.id,
            code="p2p_diaspora",
            display_name="Diaspora Transfer",
            kind="derived",
            base_service_code="p2p",
            status="active",
        )
    )
    role = Role(tenant_id=test_tenant.id, name="standard_user")
    db_session.add(role)
    await db_session.flush()
    # Granted on the BASE only — the variant has no row of its own.
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    await db_session.commit()

    resp = await async_client.get(
        f"/api/v1/services?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    role_ready = {row["code"]: row["readiness"]["role"] for row in resp.json()}

    assert role_ready["p2p"] is True
    assert role_ready["p2p_diaspora"] is True


async def test_readiness_respects_an_explicit_denial_on_a_variant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an explicit denial on the variant beats the inherited grant.

    This is the only way to withhold a variant from a role that holds its base,
    so it must show as NOT ready even though the base is granted.
    """
    from app.shared.models import Role, RolePermission

    await _seed_base(db_session, test_tenant, "p2p")
    db_session.add(
        Service(
            tenant_id=test_tenant.id,
            code="p2p_diaspora",
            display_name="Diaspora Transfer",
            kind="derived",
            base_service_code="p2p",
            status="active",
        )
    )
    role = Role(tenant_id=test_tenant.id, name="standard_user")
    db_session.add(role)
    await db_session.flush()
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    db_session.add(
        RolePermission(role_id=role.id, transaction_type="p2p_diaspora", permitted=False)
    )
    await db_session.commit()

    resp = await async_client.get(
        f"/api/v1/services?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    role_ready = {row["code"]: row["readiness"]["role"] for row in resp.json()}

    assert role_ready["p2p"] is True
    assert role_ready["p2p_diaspora"] is False


async def test_readiness_ignores_a_grant_from_an_inactive_role(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify only an ACTIVE role's grant counts as ready.

    `roles.has_permission` requires the role to be active, so a grant sitting on
    an inactive role lets nobody transact. Reporting it as ready would send the
    admin looking for the fault everywhere except the disabled role.
    """
    from app.shared.models import Role, RolePermission

    await _seed_base(db_session, test_tenant, "p2p")
    inactive = Role(tenant_id=test_tenant.id, name="retired_tier", status="inactive")
    db_session.add(inactive)
    await db_session.flush()
    db_session.add(RolePermission(role_id=inactive.id, transaction_type="p2p", permitted=True))
    await db_session.commit()

    resp = await async_client.get(
        f"/api/v1/services?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["code"] == "p2p")

    assert row["readiness"]["role"] is False
