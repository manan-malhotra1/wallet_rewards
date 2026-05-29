"""Tests for POST /api/v1/events/external — the ingestion pipeline.

Covers the scenarios listed in
docs/security/threat-models/phase-c-rewards-inflow.md §5.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    EventIngestionLog,
    RewardEvent,
    Tenant,
    User,
    Account,
)
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _seed_source(
    async_client: AsyncClient, tenant: Tenant, source_key: str
) -> None:
    """Register the source via the API so subsequent ingest calls have a target."""
    resp = await async_client.post(
        "/api/v1/events/sources",
        json={
            "tenant_id": str(tenant.id),
            "name": f"source-{source_key}",
            "source_key": source_key,
        },
    )
    assert resp.status_code == 201, resp.text


async def _seed_first_time_rule(
    async_client: AsyncClient,
    tenant: Tenant,
    *,
    transaction_type: str = "top_up",
    reward_value: str = "100",
) -> str:
    """Create a first_time rule via the API. Returns the rule_id."""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(tenant.id),
            "name": f"first-{transaction_type}",
            "rule_type": "first_time",
            "transaction_type": transaction_type,
            "reward_type": "points",
            "reward_value": reward_value,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_milestone_rule(
    async_client: AsyncClient,
    tenant: Tenant,
    *,
    transaction_type: str,
    threshold: int,
    reward_value: str,
) -> str:
    """Create a milestone rule via the API. Returns the rule_id."""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(tenant.id),
            "name": f"milestone-{transaction_type}-{threshold}",
            "rule_type": "milestone",
            "transaction_type": transaction_type,
            "count_threshold": threshold,
            "reward_type": "points",
            "reward_value": reward_value,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_event(
    *,
    source_key: str,
    tenant: Tenant,
    user: User,
    transaction_type: str = "top_up",
    amount: str = "500",
    event_id: str | None = None,
) -> dict:
    """Build a RawExternalEvent JSON body."""
    return {
        "event_id": event_id or uuid4().hex,
        "source_key": source_key,
        "tenant_id": str(tenant.id),
        "user_id": str(user.id),
        "transaction_type": transaction_type,
        "amount": amount,
        "currency": "ZAR",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _ensure_system_points_issuance(
    db_session: AsyncSession, tenant: Tenant
) -> Account:
    """Create system_points_issuance for the tenant (test helper)."""
    existing = (await db_session.execute(
        select(Account).where(
            Account.tenant_id == tenant.id,
            Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    account = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_rejects_unregistered_source(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Unknown source_key → outcome 'rejected', no reward issued."""
    response = await async_client.post(
        "/api/v1/events/external",
        json=_make_event(
            source_key="not-registered",
            tenant=test_tenant,
            user=test_user,
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "rejected"
    assert body["rejection_reason"] == "source_not_registered"


@pytest.mark.asyncio
async def test_ingest_rejects_tenant_mismatch(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
) -> None:
    """Source registered in tenant A, event claims tenant B → rejected."""
    await _seed_source(async_client, test_tenant, "mismatch-src")
    event = _make_event(
        source_key="mismatch-src",
        tenant=other_tenant,
        user=test_user,
    )
    response = await async_client.post("/api/v1/events/external", json=event)
    assert response.status_code == 200
    assert response.json()["rejection_reason"] == "source_tenant_mismatch"


@pytest.mark.asyncio
async def test_ingest_dedupes_replayed_event(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001 — ensures points account exists
) -> None:
    """Same (source_key, event_id) replay → outcome 'duplicate', no new reward."""
    await _ensure_system_points_issuance(db_session, test_tenant)
    await _seed_source(async_client, test_tenant, "dedup-src")
    await _seed_first_time_rule(async_client, test_tenant, transaction_type="top_up")

    event = _make_event(
        source_key="dedup-src",
        tenant=test_tenant,
        user=test_user,
        transaction_type="top_up",
    )

    first = await async_client.post("/api/v1/events/external", json=event)
    assert first.json()["outcome"] == "processed"
    assert len(first.json()["rules_fired"]) == 1

    second = await async_client.post("/api/v1/events/external", json=event)
    assert second.json()["outcome"] == "duplicate"
    assert second.json()["rules_fired"] == []

    # Only ONE reward_events row exists.
    rewards = (await db_session.execute(
        select(RewardEvent).where(RewardEvent.user_id == test_user.id)
    )).scalars().all()
    assert len(rewards) == 1


@pytest.mark.asyncio
async def test_first_time_rule_fires_exactly_once(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
) -> None:
    """First-time rule fires on event 1; second qualifying event yields no reward."""
    await _ensure_system_points_issuance(db_session, test_tenant)
    await _seed_source(async_client, test_tenant, "first-src")
    await _seed_first_time_rule(async_client, test_tenant, transaction_type="top_up")

    e1 = _make_event(
        source_key="first-src",
        tenant=test_tenant,
        user=test_user,
        transaction_type="top_up",
    )
    e2 = _make_event(
        source_key="first-src",
        tenant=test_tenant,
        user=test_user,
        transaction_type="top_up",
    )

    r1 = (await async_client.post("/api/v1/events/external", json=e1)).json()
    r2 = (await async_client.post("/api/v1/events/external", json=e2)).json()

    assert len(r1["rules_fired"]) == 1
    assert len(r2["rules_fired"]) == 0


@pytest.mark.asyncio
async def test_milestone_rule_fires_at_threshold_and_resets(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
) -> None:
    """Milestone(threshold=3) fires on the 3rd event, then resets — 6th event fires again."""
    await _ensure_system_points_issuance(db_session, test_tenant)
    await _seed_source(async_client, test_tenant, "milestone-src")
    await _seed_milestone_rule(
        async_client,
        test_tenant,
        transaction_type="p2p",
        threshold=3,
        reward_value="50",
    )

    outcomes = []
    for _ in range(6):
        evt = _make_event(
            source_key="milestone-src",
            tenant=test_tenant,
            user=test_user,
            transaction_type="p2p",
        )
        resp = await async_client.post("/api/v1/events/external", json=evt)
        outcomes.append(len(resp.json()["rules_fired"]))

    # Events 1, 2 → no fire. Event 3 → fire. Events 4, 5 → no fire. Event 6 → fire.
    assert outcomes == [0, 0, 1, 0, 0, 1]


@pytest.mark.asyncio
async def test_rule_only_matches_correct_transaction_type(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
) -> None:
    """Rule bound to 'top_up' does not fire on 'p2p' events."""
    await _ensure_system_points_issuance(db_session, test_tenant)
    await _seed_source(async_client, test_tenant, "type-src")
    await _seed_first_time_rule(async_client, test_tenant, transaction_type="top_up")

    p2p_event = _make_event(
        source_key="type-src",
        tenant=test_tenant,
        user=test_user,
        transaction_type="p2p",
    )
    resp = await async_client.post("/api/v1/events/external", json=p2p_event)
    assert resp.json()["rules_fired"] == []


@pytest.mark.asyncio
async def test_ingestion_log_records_outcome(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
) -> None:
    """Every received event leaves an event_ingestion_log row."""
    await _ensure_system_points_issuance(db_session, test_tenant)
    await _seed_source(async_client, test_tenant, "log-src")
    await _seed_first_time_rule(async_client, test_tenant)

    evt = _make_event(
        source_key="log-src", tenant=test_tenant, user=test_user
    )
    await async_client.post("/api/v1/events/external", json=evt)

    log = (await db_session.execute(
        select(EventIngestionLog).where(
            EventIngestionLog.source_key == "log-src",
            EventIngestionLog.external_event_id == evt["event_id"],
        )
    )).scalar_one_or_none()
    assert log is not None
    assert log.status == "PROCESSED"
