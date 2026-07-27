"""Baseline (synthesized) config version-history tests (Pricing v2 Epic 22).

A live config created directly by the seed (never through the maker-checker) has
ZERO applied create/update requests, so its scope's version history is empty and
the UI version panel renders blank. `list_config_history_for_scope` therefore
synthesizes a SINGLE "current" baseline version from the live config row(s) when
— and only when — the applied-request list is empty. Read-time only: nothing is
persisted.

Covers: a single-band scope (limit) with no applied history → one synthesized
entry mirroring the live row; a multi-band scope (pricing) → one synthesized
entry whose payload gathers ALL the scope's bands, amount-ascending; a scope
WITH applied requests → real entries only, no baseline appended; and tenant
isolation / unknown target still 404.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import LimitConfig, PricingConfig, Tenant

pytestmark = pytest.mark.asyncio

MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"


def _maker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["platform-admin"], sub=MAKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _checker(make_admin_token: Callable[..., str]) -> dict[str, str]:
    token = make_admin_token(roles=["config-approver"], sub=CHECKER_SUB)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _history_url(tenant: Tenant, config_type: str, target_config_id: str) -> str:
    return (
        f"/api/v1/config-requests/history?tenant_id={tenant.id}"
        f"&config_type={config_type}&target_config_id={target_config_id}"
    )


# -----------------------------------------------------------------------------
# Single-band: a seeded limit scope with NO applied requests
# -----------------------------------------------------------------------------


async def test_single_band_scope_without_history_synthesizes_baseline(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A live limit row created outside maker-checker → 1 synthesized baseline."""
    live = LimitConfig(
        tenant_id=test_tenant.id,
        transaction_type="p2p",
        account_type="financial_wallet",
        currency="GBP",
        max_amount=Decimal("5000"),
    )
    db_session.add(live)
    await db_session.commit()
    await db_session.refresh(live)

    resp = await async_client.get(
        _history_url(test_tenant, "limit", str(live.id)), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()

    assert len(history) == 1
    entry = history[0]
    assert entry["synthesized"] is True
    assert entry["status"] == "APPLIED"
    assert entry["operation"] == "create"
    assert entry["target_config_id"] is None
    assert entry["revision"] == 1
    assert entry["maker_admin_id"] == "system"
    assert entry["checker_admin_id"] is None
    assert entry["reviews"] == []
    assert entry["revisions"] == []
    # The synthetic id is the live row's own id (stable/real, but NOT a request id).
    assert entry["id"] == str(live.id)
    # Payload mirrors the live values in create-schema shape.
    assert entry["payload"]["transaction_type"] == "p2p"
    assert entry["payload"]["account_type"] == "financial_wallet"
    assert entry["payload"]["currency"] == "GBP"
    assert Decimal(entry["payload"]["max_amount"]) == Decimal("5000")


# -----------------------------------------------------------------------------
# Multi-band: a seeded pricing scope with several live bands, NO applied requests
# -----------------------------------------------------------------------------


async def test_multi_band_scope_without_history_synthesizes_all_bands(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A live pricing schedule (3 bands) with no applied history → 1 baseline.

    The single synthesized entry's payload gathers EVERY band sharing the scope,
    ordered by amount_from ascending — regardless of DB insertion order.
    """
    scope = dict(
        tenant_id=test_tenant.id,
        transaction_type="cashout",
        account_type="financial_wallet",
        currency="ZAR",
        user_type=None,
    )
    # Insert deliberately OUT of amount order to prove the synthesis sorts.
    bands = [
        PricingConfig(**scope, amount_from=Decimal("201"), amount_to=None,
                      fixed_fee=Decimal("3")),
        PricingConfig(**scope, amount_from=Decimal("0"), amount_to=Decimal("100"),
                      fixed_fee=Decimal("1")),
        PricingConfig(**scope, amount_from=Decimal("101"), amount_to=Decimal("200"),
                      fixed_fee=Decimal("2")),
    ]
    for band in bands:
        db_session.add(band)
    await db_session.commit()
    for band in bands:
        await db_session.refresh(band)

    # Target ANY band in the scope; the whole scope's schedule is reconstructed.
    target_id = str(bands[0].id)
    resp = await async_client.get(
        _history_url(test_tenant, "pricing", target_id), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()

    assert len(history) == 1
    entry = history[0]
    assert entry["synthesized"] is True
    assert entry["status"] == "APPLIED"
    assert entry["operation"] == "create"

    payload_bands = entry["payload"]["bands"]
    assert len(payload_bands) == 3
    # Ordered by amount_from ascending, not DB insertion order.
    froms = [Decimal(b["amount_from"]) for b in payload_bands]
    assert froms == [Decimal("0"), Decimal("101"), Decimal("201")]
    fixed = [Decimal(b["fixed_fee"]) for b in payload_bands]
    assert fixed == [Decimal("1"), Decimal("2"), Decimal("3")]
    assert all(b["currency"] == "ZAR" for b in payload_bands)
    assert all(b["transaction_type"] == "cashout" for b in payload_bands)


# -----------------------------------------------------------------------------
# Regression: a live row whose values would FAIL its create schema still
# synthesizes (baseline mirrors live values, never re-validates them)
# -----------------------------------------------------------------------------


async def test_baseline_mirrors_live_row_that_fails_create_schema(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An all-null-caps limit (which `LimitConfigCreateRequest` rejects) → baseline.

    The live row legitimately holds state the CREATE schema forbids ("At least
    one cap must be set."). The baseline must mirror it faithfully via
    model_construct, not 500 by re-running the create validators.
    """
    live = LimitConfig(
        tenant_id=test_tenant.id,
        transaction_type="p2p",
        account_type="financial_wallet",
        currency="KES",
        # Every cap NULL — a create payload could never be proposed this way.
        max_amount=None,
        min_amount=None,
    )
    db_session.add(live)
    await db_session.commit()
    await db_session.refresh(live)

    resp = await async_client.get(
        _history_url(test_tenant, "limit", str(live.id)), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()

    assert len(history) == 1
    entry = history[0]
    assert entry["synthesized"] is True
    assert entry["status"] == "APPLIED"
    # Live values mirrored verbatim — all caps null, scope intact.
    assert entry["payload"]["currency"] == "KES"
    assert entry["payload"]["max_amount"] is None
    assert entry["payload"]["daily_count_cap"] is None
    assert entry["payload"]["monthly_value_cap"] is None


# -----------------------------------------------------------------------------
# A scope WITH applied requests: unchanged — real entries, no baseline appended
# -----------------------------------------------------------------------------


async def test_scope_with_applied_history_has_no_synthesized_baseline(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An APPLIED create through the workflow → real entry, synthesized=False."""
    body = {
        "config_type": "limit",
        "operation": "create",
        "payload": {
            "tenant_id": str(test_tenant.id),
            "transaction_type": "p2p",
            "account_type": "financial_wallet",
            "currency": "USD",
            "max_amount": "1234",
        },
    }
    created = await async_client.post(
        f"/api/v1/config-requests?tenant_id={test_tenant.id}",
        content=json.dumps(body),
        headers=_maker(make_admin_token),
    )
    assert created.status_code == 201, created.text
    approve = await async_client.post(
        f"/api/v1/config-requests/{created.json()['id']}/approve?tenant_id={test_tenant.id}",
        headers=_checker(make_admin_token),
    )
    assert approve.status_code == 200, approve.text

    live_id = (
        await db_session.execute(
            select(LimitConfig.id).where(
                LimitConfig.tenant_id == test_tenant.id, LimitConfig.currency == "USD"
            )
        )
    ).scalar_one()

    resp = await async_client.get(
        _history_url(test_tenant, "limit", str(live_id)), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 200, resp.text
    history = resp.json()

    # Exactly the one real applied entry — no synthetic baseline appended.
    assert len(history) == 1
    assert history[0]["synthesized"] is False
    assert history[0]["status"] == "APPLIED"
    assert history[0]["maker_admin_id"] == MAKER_SUB


# -----------------------------------------------------------------------------
# Tenant isolation + unknown target still 404 on the baseline path
# -----------------------------------------------------------------------------


async def test_baseline_tenant_isolation_is_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A live row in tenant A queried under tenant B's id → 404 (not synthesized)."""
    live = LimitConfig(
        tenant_id=test_tenant.id,
        transaction_type="p2p",
        account_type="financial_wallet",
        currency="GBP",
        max_amount=Decimal("5000"),
    )
    db_session.add(live)
    await db_session.commit()
    await db_session.refresh(live)

    resp = await async_client.get(
        _history_url(other_tenant, "limit", str(live.id)), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "config_request_target_not_found"


async def test_baseline_unknown_target_is_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """An unknown target id → 404, never a fabricated baseline."""
    resp = await async_client.get(
        _history_url(test_tenant, "limit", str(uuid4())), headers=_maker(make_admin_token)
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "config_request_target_not_found"
