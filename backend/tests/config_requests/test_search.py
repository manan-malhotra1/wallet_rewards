"""Server-side search over the config-requests queue (B7.2c).

Mirrors the money/user-operations search contract: `q` filters the list and
/counts endpoints across the whole queue (request id, maker, config type,
payload text).
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


async def _propose(
    client: AsyncClient, tenant: Tenant, header: dict[str, str], transaction_type: str
) -> str:
    resp = await client.post(
        _url(tenant),
        content=json.dumps(_pricing_payload(tenant.id, transaction_type)),
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_q_matches_payload_text(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify q matches a value inside the payload (the scoped transaction type)."""
    header = _maker(make_admin_token)
    wanted = await _propose(async_client, test_tenant, header, "cash_out")
    await _propose(async_client, test_tenant, header, "p2p")

    resp = await async_client.get(_url(test_tenant) + "&q=cash_out", headers=header)
    assert resp.status_code == 200
    assert [req["id"] for req in resp.json()] == [wanted]


@pytest.mark.asyncio
async def test_q_with_no_match_returns_empty(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify an unmatched q yields an empty list, not an error."""
    header = _maker(make_admin_token)
    await _propose(async_client, test_tenant, header, "cash_in")
    resp = await async_client.get(_url(test_tenant) + "&q=zzz-no-such-thing", headers=header)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_counts_apply_q(
    async_client: AsyncClient, test_tenant: Tenant, make_admin_token: Callable[..., str]
) -> None:
    """Verify /counts filters by q, so a searching page's pager stays correct."""
    header = _maker(make_admin_token)
    await _propose(async_client, test_tenant, header, "cash_out")
    await _propose(async_client, test_tenant, header, "p2p")

    resp = await async_client.get(_url(test_tenant, "/counts") + "&q=cash_out", headers=header)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
