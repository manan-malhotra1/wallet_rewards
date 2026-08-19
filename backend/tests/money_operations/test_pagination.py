"""Windowed listing + cheap status counts for the money-operations queue (B7.1).

The unified approvals page must never fetch a full queue: the list endpoint
takes limit/offset, and a /counts endpoint answers the tab-bar and status
segment counts from one grouped query instead of fetching every row.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant
from tests.money_operations.conftest import ops_url, propose


async def _propose_mirrors(
    client: AsyncClient, tenant: Tenant, maker_header: dict[str, str], names: list[str]
) -> list[str]:
    """Propose one create_bank_mirror per name; return request ids in propose order."""
    ids: list[str] = []
    for name in names:
        proposed = await propose(
            client, tenant, maker_header, "create_bank_mirror", {"currency": "ZAR", "name": name}
        )
        ids.append(proposed["id"])
    return ids


@pytest.mark.asyncio
async def test_list_windows_newest_first(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify limit/offset slice the newest-first list into stable windows."""
    ids = await _propose_mirrors(async_client, test_tenant, maker_header, ["a", "b", "c"])

    resp = await async_client.get(ops_url(test_tenant) + "&limit=2", headers=maker_header)
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [ids[2], ids[1]]

    resp = await async_client.get(
        ops_url(test_tenant) + "&limit=2&offset=2", headers=maker_header
    )
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [ids[0]]


@pytest.mark.asyncio
async def test_list_window_bounds_422(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify out-of-bounds limit/offset are rejected with 422, not clamped."""
    for query in ("&limit=0", "&limit=501", "&offset=-1"):
        resp = await async_client.get(ops_url(test_tenant) + query, headers=maker_header)
        assert resp.status_code == 422, query


@pytest.mark.asyncio
async def test_list_window_is_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a windowed list never leaks another tenant's rows."""
    await _propose_mirrors(async_client, test_tenant, maker_header, ["only-a"])
    resp = await async_client.get(ops_url(other_tenant) + "&limit=10", headers=maker_header)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_counts_by_status(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify /counts returns the queue total and a per-status breakdown."""
    ids = await _propose_mirrors(async_client, test_tenant, maker_header, ["keep", "drop"])
    resp = await async_client.post(
        ops_url(test_tenant, f"/{ids[1]}/withdraw"), headers=maker_header
    )
    assert resp.status_code == 200

    resp = await async_client.get(ops_url(test_tenant, "/counts"), headers=maker_header)
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
    maker_header: dict[str, str],
) -> None:
    """Verify /counts never counts another tenant's rows."""
    await _propose_mirrors(async_client, test_tenant, maker_header, ["a-only"])
    resp = await async_client.get(ops_url(other_tenant, "/counts"), headers=maker_header)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_counts_require_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify /counts rejects unauthenticated callers."""
    resp = await async_client.get(ops_url(test_tenant, "/counts"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_counts_require_platform_admin(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token
) -> None:
    """Verify /counts rejects an admin without the platform-admin role."""
    header = {"Authorization": f"Bearer {make_admin_token(roles=['support-agent'])}"}
    resp = await async_client.get(ops_url(test_tenant, "/counts"), headers=header)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_counts_reject_malformed_tenant_id(
    async_client: AsyncClient, maker_header: dict[str, str]
) -> None:
    """Verify /counts 422s on a tenant_id that is not a UUID."""
    resp = await async_client.get(
        "/api/v1/money-operations/counts?tenant_id=not-a-uuid", headers=maker_header
    )
    assert resp.status_code == 422
