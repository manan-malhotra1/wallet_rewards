"""Tests for the value_based rule type — Epic 10 (WAL-74).

Drives the engine via the public events/external HTTP path so the
candidate query + dispatcher + branch are all exercised end-to-end.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Tenant,
    User,
)


async def _ensure_system_points(session: AsyncSession, tenant: Tenant) -> None:
    """Create the tenant's system_points_issuance master account."""
    existing = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Account(
                tenant_id=tenant.id,
                account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
                currency="PTS",
            )
        )
        await session.commit()


async def _register_source(client: AsyncClient, tenant: Tenant, key: str) -> None:
    """Register the dev event source so subsequent ingest calls work."""
    resp = await client.post(
        "/api/v1/events/sources",
        json={"tenant_id": str(tenant.id), "name": f"src-{key}", "source_key": key},
    )
    assert resp.status_code == 201, resp.text


async def _create_value_based_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    transaction_type: str = "top_up",
    min_amount: str = "100",
    reward_value: str = "50",
    stop_after_n_triggers: int | None = None,
) -> None:
    """Create a value_based rule via the public API."""
    body = {
        "tenant_id": str(tenant.id),
        "name": f"value-{uuid4().hex[:6]}",
        "rule_type": "value_based",
        "transaction_type": transaction_type,
        "min_amount": min_amount,
        "reward_type": "points",
        "reward_value": reward_value,
    }
    if stop_after_n_triggers is not None:
        body["stop_after_n_triggers"] = stop_after_n_triggers
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text


def _event(
    *, tenant: Tenant, user: User, source_key: str, amount: str
) -> dict:
    """Build the RawExternalEvent body."""
    return {
        "event_id": uuid4().hex,
        "source_key": source_key,
        "tenant_id": str(tenant.id),
        "user_id": str(user.id),
        "transaction_type": "top_up",
        "amount": amount,
        "currency": "ZAR",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@pytest.mark.asyncio
async def test_value_based_fires_when_amount_meets_threshold(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """min_amount=100; a R 500 event fires the rule."""
    await _ensure_system_points(db_session, test_tenant)
    await _register_source(async_client, test_tenant, "vb-src-1")
    await _create_value_based_rule(async_client, test_tenant, min_amount="100")

    # Also need the user's points account so issuance can credit.
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/events/external",
        json=_event(tenant=test_tenant, user=test_user, source_key="vb-src-1", amount="500"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "processed"
    assert len(resp.json()["rules_fired"]) == 1


@pytest.mark.asyncio
async def test_value_based_does_not_fire_below_threshold(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """min_amount=100; a R 50 event does NOT fire."""
    await _ensure_system_points(db_session, test_tenant)
    await _register_source(async_client, test_tenant, "vb-src-2")
    await _create_value_based_rule(async_client, test_tenant, min_amount="100")

    resp = await async_client.post(
        "/api/v1/events/external",
        json=_event(tenant=test_tenant, user=test_user, source_key="vb-src-2", amount="50"),
    )
    assert resp.status_code == 200
    assert resp.json()["rules_fired"] == []


@pytest.mark.asyncio
async def test_value_based_stop_after_n_triggers(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """stop_after_n_triggers=2; events 1+2 fire, event 3 doesn't."""
    await _ensure_system_points(db_session, test_tenant)
    await _register_source(async_client, test_tenant, "vb-src-3")
    await _create_value_based_rule(
        async_client, test_tenant, min_amount="100", stop_after_n_triggers=2
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    await db_session.commit()

    outcomes = []
    for _ in range(3):
        resp = await async_client.post(
            "/api/v1/events/external",
            json=_event(
                tenant=test_tenant, user=test_user, source_key="vb-src-3", amount="500"
            ),
        )
        outcomes.append(len(resp.json()["rules_fired"]))
    assert outcomes == [1, 1, 0]


@pytest.mark.asyncio
async def test_value_based_requires_min_amount_on_create(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Creating a value_based rule without min_amount → 422."""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "bad-vb",
            "rule_type": "value_based",
            "transaction_type": "top_up",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422
