"""Windowed listing + cheap status counts for the config-requests queue (B7.1).

Mirrors the money/user-operations pagination contract: the list endpoint takes
limit/offset, and /counts answers the approvals tab-bar and status segment
counts from one grouped query instead of fetching every row.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant

MAKER_SUB = "11111111-1111-4000-8000-000000000001"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


def _pricing_payload(tenant_id: UUID, transaction_type: str) -> dict:
    """A pricing create for one transaction_type — distinct types dodge the
    one-open-request-per-scope guard when proposing several requests."""
    return {
        "config_type": "pricing",
        "operation": "create",
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": transaction_type,
            "account_type": "financial_wallet",
            "currency": "ZAR",
            "fixed_fee": "5",
        },
    }


async def _propose_many(
    client: AsyncClient, tenant: Tenant, header: dict[str, str], transaction_types: list[str]
) -> list[str]:
    """Propose one pricing create per transaction type; return ids in propose order."""
    ids: list[str] = []
    for transaction_type in transaction_types:
        resp = await client.post(
            _url(tenant),
            content=json.dumps(_pricing_payload(tenant.id, transaction_type)),
            headers=header,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    return ids


@pytest.mark.asyncio
async def test_list_windows_newest_first(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify limit/offset slice the newest-first list into stable windows."""
    header = _maker(make_admin_token)
    ids = await _propose_many(
        async_client, test_tenant, header, ["cash_in", "cash_out", "p2p"]
    )

    resp = await async_client.get(_url(test_tenant) + "&limit=2", headers=header)
    assert resp.status_code == 200
    assert [req["id"] for req in resp.json()] == [ids[2], ids[1]]

    resp = await async_client.get(_url(test_tenant) + "&limit=2&offset=2", headers=header)
    assert resp.status_code == 200
    assert [req["id"] for req in resp.json()] == [ids[0]]


@pytest.mark.asyncio
async def test_list_window_bounds_422(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify out-of-bounds limit/offset are rejected with 422, not clamped."""
    header = _maker(make_admin_token)
    for query in ("&limit=0", "&limit=501", "&offset=-1"):
        resp = await async_client.get(_url(test_tenant) + query, headers=header)
        assert resp.status_code == 422, query


@pytest.mark.asyncio
async def test_counts_by_status(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify /counts returns the queue total and a per-status breakdown."""
    header = _maker(make_admin_token)
    ids = await _propose_many(async_client, test_tenant, header, ["cash_in", "cash_out"])
    resp = await async_client.post(_url(test_tenant, f"/{ids[1]}/withdraw"), headers=header)
    assert resp.status_code == 200

    resp = await async_client.get(_url(test_tenant, "/counts"), headers=header)
    assert resp.status_code == 200
    counts = resp.json()
    assert counts["total"] == 2
    assert counts["by_status"] == {
        "PENDING": 1,
        "CHANGES_REQUESTED": 0,
        "APPLIED": 0,
        "WITHDRAWN": 1,
    }


@pytest.mark.asyncio
async def test_counts_are_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify /counts never counts another tenant's rows."""
    header = _maker(make_admin_token)
    await _propose_many(async_client, test_tenant, header, ["cash_in"])
    resp = await async_client.get(_url(other_tenant, "/counts"), headers=header)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_window_is_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify a windowed list never leaks another tenant's rows."""
    header = _maker(make_admin_token)
    await _propose_many(async_client, test_tenant, header, ["cash_in"])
    resp = await async_client.get(_url(other_tenant) + "&limit=10", headers=header)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_counts_require_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify /counts rejects unauthenticated callers."""
    resp = await async_client.get(_url(test_tenant, "/counts"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_counts_require_platform_admin(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify /counts rejects an admin without the platform-admin role."""
    header = {"Authorization": f"Bearer {make_admin_token(roles=['support-agent'])}"}
    resp = await async_client.get(_url(test_tenant, "/counts"), headers=header)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_counts_reject_malformed_tenant_id(
    async_client: AsyncClient, make_admin_token: Callable[..., str]
) -> None:
    """Verify /counts 422s on a tenant_id that is not a UUID."""
    resp = await async_client.get(
        "/api/v1/config-requests/counts?tenant_id=not-a-uuid",
        headers=_maker(make_admin_token),
    )
    assert resp.status_code == 422
