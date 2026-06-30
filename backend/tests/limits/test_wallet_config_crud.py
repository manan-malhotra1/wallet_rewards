"""Endpoint tests for the wallet limit config admin CRUD (WAL-237).

Covers POST/GET/DELETE /api/v1/limits/wallet-configs: happy path, auth (401),
permission (403), validation (422), duplicate (409), and tenant isolation.
Also checks the service-wise /configs endpoint now accepts weekly/monthly caps.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant

WALLET_URL = "/api/v1/limits/wallet-configs"
CONFIG_URL = "/api/v1/limits/configs"


def _body(tenant_id, **caps) -> dict:
    return {"tenant_id": str(tenant_id), "currency": "ZAR", **caps}


@pytest.mark.asyncio
async def test_create_wallet_config_happy(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """Admin creates a wallet config → 201 with the persisted caps."""
    resp = await async_client.post(
        WALLET_URL,
        headers=admin_auth_header,
        json=_body(test_tenant.id, max_balance="50000", send_daily_value_cap="10000"),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["currency"] == "ZAR"
    assert Decimal(str(body["max_balance"])) == Decimal("50000")
    assert Decimal(str(body["send_daily_value_cap"])) == Decimal("10000")
    assert body["receive_daily_count_cap"] is None


@pytest.mark.asyncio
async def test_create_requires_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """No bearer token → 401."""
    resp = await async_client.post(WALLET_URL, json=_body(test_tenant.id, max_balance="100"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_requires_admin_role(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A token without platform-admin → 403."""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.post(
        WALLET_URL,
        headers={"Authorization": f"Bearer {token}"},
        json=_body(test_tenant.id, max_balance="100"),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_rejects_empty_config(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """A config with no caps set → 422."""
    resp = await async_client.post(
        WALLET_URL, headers=admin_auth_header, json=_body(test_tenant.id)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_non_positive_max_balance(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """max_balance must be > 0 → 422."""
    resp = await async_client.post(
        WALLET_URL, headers=admin_auth_header, json=_body(test_tenant.id, max_balance="0")
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_currency_returns_409(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """One wallet config per (tenant, currency) → second is 409."""
    first = await async_client.post(
        WALLET_URL, headers=admin_auth_header, json=_body(test_tenant.id, max_balance="100")
    )
    assert first.status_code == 201
    dup = await async_client.post(
        WALLET_URL, headers=admin_auth_header, json=_body(test_tenant.id, max_balance="200")
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_list_and_delete(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """Create → list shows it → delete → list empty; deleting again 404s."""
    created = await async_client.post(
        WALLET_URL, headers=admin_auth_header, json=_body(test_tenant.id, max_balance="100")
    )
    config_id = created.json()["id"]

    listed = await async_client.get(
        WALLET_URL, headers=admin_auth_header, params={"tenant_id": str(test_tenant.id)}
    )
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [config_id]

    deleted = await async_client.delete(
        f"{WALLET_URL}/{config_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert deleted.status_code == 204

    gone = await async_client.delete(
        f"{WALLET_URL}/{config_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_tenant_isolation(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A config in one tenant is invisible / undeletable from another tenant."""
    created = await async_client.post(
        WALLET_URL, headers=admin_auth_header, json=_body(test_tenant.id, max_balance="100")
    )
    config_id = created.json()["id"]

    # Listing the other tenant shows nothing.
    other_list = await async_client.get(
        WALLET_URL, headers=admin_auth_header, params={"tenant_id": str(other_tenant.id)}
    )
    assert other_list.json() == []

    # Deleting it under the wrong tenant → 404 (not found in that scope).
    cross = await async_client.delete(
        f"{WALLET_URL}/{config_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
    )
    assert cross.status_code == 404


@pytest.mark.asyncio
async def test_service_config_accepts_weekly_monthly(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """The service-wise /configs endpoint now persists weekly + monthly caps."""
    resp = await async_client.post(
        CONFIG_URL,
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "transaction_type": "p2p",
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "weekly_count_cap": 5,
            "monthly_value_cap": "1000",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["weekly_count_cap"] == 5
    assert Decimal(str(body["monthly_value_cap"])) == Decimal("1000")
    assert body["daily_count_cap"] is None
