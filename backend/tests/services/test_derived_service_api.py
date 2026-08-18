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
