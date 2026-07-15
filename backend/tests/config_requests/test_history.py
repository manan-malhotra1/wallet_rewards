"""Config version-history-by-scope read endpoint tests (Pricing v2 Epic 22).

A live config's identity is its SCOPE, not its row id — an approved `update`
atomically REPLACES the scope (new row id each time). The version history of a
live config is therefore every APPLIED create/update request of that config_type
whose payload scope matches the live row's scope, chronologically; the most
recent entry mirrors the current live values.

Covers: a create + two updates on the SAME scope → three chronological entries
with distinct payloads (last == live); a differently-scoped config excluded;
a missing target → 404; the static `/history` route not being shadowed by the
dynamic `/{request_id}` route; and auth / tenant isolation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import LimitConfig, Tenant

pytestmark = pytest.mark.asyncio

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _url(tenant: Tenant, suffix: str = "") -> str:
    return f"/api/v1/config-requests{suffix}?tenant_id={tenant.id}"


def _history_url(tenant: Tenant, config_type: str, target_config_id: str) -> str:
    return (
        f"/api/v1/config-requests/history?tenant_id={tenant.id}"
        f"&config_type={config_type}&target_config_id={target_config_id}"
    )


def _limit_body(
    tenant_id: UUID,
    *,
    operation: str,
    max_amount: str,
    currency: str = "ZAR",
    target: str | None = None,
) -> dict:
    body: dict = {
        "config_type": "limit",
        "operation": operation,
        "payload": {
            "tenant_id": str(tenant_id),
            "transaction_type": "p2p",
            "account_type": "financial_wallet",
            "currency": currency,
            "max_amount": max_amount,
        },
    }
    if target is not None:
        body["target_config_id"] = target
    return body


async def _propose(
    client: AsyncClient, tenant: Tenant, body: dict, headers: dict[str, str]
) -> object:
    return await client.post(_url(tenant), content=json.dumps(body), headers=headers)


async def _approve(
    client: AsyncClient, tenant: Tenant, request_id: str, headers: dict[str, str]
) -> None:
    resp = await client.post(_url(tenant, f"/{request_id}/approve"), headers=headers)
    assert resp.status_code == 200, resp.text


async def _live_limit_id(
    db_session: AsyncSession, tenant: Tenant, currency: str = "ZAR"
) -> str:
    """Return the id of the single live limit row for the currency scope."""
    row = (
        await db_session.execute(
            select(LimitConfig).where(
                LimitConfig.tenant_id == tenant.id, LimitConfig.currency == currency
            )
        )
    ).scalar_one()
    return str(row.id)


async def _create_and_update_twice(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> str:
    """Apply a create (1000) then two updates (2000, 3000) on the same scope.

    Each approved update atomically replaces the scope, so the live row id
    changes; returns the CURRENT live row id after the second update.
    """
    created = await _propose(
        async_client,
        tenant,
        _limit_body(tenant.id, operation="create", max_amount="1000"),
        _maker(make_admin_token),
    )
    assert created.status_code == 201, created.text
    await _approve(async_client, tenant, created.json()["id"], _checker(make_admin_token))

    for new_cap in ("2000", "3000"):
        target = await _live_limit_id(db_session, tenant)
        updated = await _propose(
            async_client,
            tenant,
            _limit_body(tenant.id, operation="update", max_amount=new_cap, target=target),
            _maker(make_admin_token),
        )
        assert updated.status_code == 201, updated.text
        await _approve(async_client, tenant, updated.json()["id"], _checker(make_admin_token))

    return await _live_limit_id(db_session, tenant)


# -----------------------------------------------------------------------------
# Happy path: three chronological versions, last == current live
# -----------------------------------------------------------------------------


async def test_history_returns_all_versions_chronologically(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """create + 2 updates on one scope → 3 entries oldest-first, last == live cap."""
    live_id = await _create_and_update_twice(
        async_client, db_session, test_tenant, make_admin_token
    )

    resp = await async_client.get(
        _history_url(test_tenant, "limit", live_id), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()

    assert len(history) == 3
    caps = [entry["payload"]["max_amount"] for entry in history]
    assert caps == [str(Decimal("1000")), str(Decimal("2000")), str(Decimal("3000"))]
    # All APPLIED create/update of this scope.
    assert {e["status"] for e in history} == {"APPLIED"}
    assert [e["operation"] for e in history] == ["create", "update", "update"]

    # The most recent entry mirrors the current live config.
    live_cap = (
        await db_session.execute(
            select(LimitConfig.max_amount).where(LimitConfig.id == UUID(live_id))
        )
    ).scalar_one()
    assert Decimal(history[-1]["payload"]["max_amount"]) == live_cap


# -----------------------------------------------------------------------------
# Scope isolation: a differently-scoped config is excluded
# -----------------------------------------------------------------------------


async def test_history_excludes_other_scope(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A limit config of a DIFFERENT currency scope is not in this scope's history."""
    live_id = await _create_and_update_twice(
        async_client, db_session, test_tenant, make_admin_token
    )

    # A separate limit config for a different currency (different scope).
    other = await _propose(
        async_client,
        test_tenant,
        _limit_body(test_tenant.id, operation="create", max_amount="999", currency="USD"),
        _maker(make_admin_token),
    )
    assert other.status_code == 201, other.text
    await _approve(async_client, test_tenant, other.json()["id"], _checker(make_admin_token))

    resp = await async_client.get(
        _history_url(test_tenant, "limit", live_id), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()

    # Still only the 3 ZAR versions — the USD config is a different scope.
    assert len(history) == 3
    assert all(e["payload"]["currency"] == "ZAR" for e in history)


# -----------------------------------------------------------------------------
# 404: absent / bad target
# -----------------------------------------------------------------------------


async def test_history_absent_target_is_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A target_config_id that isn't a live row in this tenant → 404."""
    resp = await async_client.get(
        _history_url(test_tenant, "limit", str(uuid4())), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "config_request_target_not_found"


# -----------------------------------------------------------------------------
# Routing: /history is not captured by the dynamic /{request_id} route
# -----------------------------------------------------------------------------


async def test_history_route_not_shadowed_by_request_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Hitting `/history` resolves to the history handler, not `GET /{request_id}`.

    If it were shadowed, "history" would be parsed as a request_id UUID and the
    request would 422 on the path param. A 200 with a list proves the static
    route wins.
    """
    live_id = await _create_and_update_twice(
        async_client, db_session, test_tenant, make_admin_token
    )
    resp = await async_client.get(
        _history_url(test_tenant, "limit", live_id), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# -----------------------------------------------------------------------------
# Auth / tenant isolation
# -----------------------------------------------------------------------------


async def test_history_requires_auth(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """No bearer token → 401."""
    resp = await async_client.get(_history_url(test_tenant, "limit", str(uuid4())))
    assert resp.status_code == 401, resp.text


async def test_history_wrong_role_is_403(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A token without the admin role required by the read → 403."""
    token = make_admin_token(roles=["auditor"], sub=MAKER_SUB)
    resp = await async_client.get(
        _history_url(test_tenant, "limit", str(uuid4())),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


async def test_history_tenant_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A live row in tenant A queried under tenant B's id → 404 (not found there)."""
    live_id = await _create_and_update_twice(
        async_client, db_session, test_tenant, make_admin_token
    )
    resp = await async_client.get(
        _history_url(other_tenant, "limit", live_id), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "config_request_target_not_found"
