"""Tests for the campaign rule type — Epic 10 (WAL-76).

Campaign rules fire once per user, only within
[campaign_start_date, campaign_end_date]. Outside the window the rule
is a no-op.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


async def _user_points_account(session: AsyncSession, tenant: Tenant, user: User) -> None:
    """Create a points account for the user so issuance can credit."""
    session.add(
        Account(
            tenant_id=tenant.id,
            user_id=user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    await session.commit()


async def _register_source(client: AsyncClient, tenant: Tenant, key: str) -> None:
    """Register the dev event source."""
    resp = await client.post(
        "/api/v1/events/sources",
        json={"tenant_id": str(tenant.id), "name": f"src-{key}", "source_key": key},
    )
    assert resp.status_code == 201, resp.text


async def _create_campaign_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    start: date,
    end: date,
    transaction_type: str = "top_up",
    reward_value: str = "100",
) -> None:
    """Create a campaign rule with a date window."""
    body = {
        "tenant_id": str(tenant.id),
        "name": f"camp-{uuid4().hex[:6]}",
        "rule_type": "campaign",
        "transaction_type": transaction_type,
        "campaign_start_date": start.isoformat(),
        "campaign_end_date": end.isoformat(),
        "reward_type": "points",
        "reward_value": reward_value,
    }
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text


def _event_at(
    *, tenant: Tenant, user: User, source_key: str, when: datetime
) -> dict:
    """Build a RawExternalEvent with an explicit timestamp."""
    return {
        "event_id": uuid4().hex,
        "source_key": source_key,
        "tenant_id": str(tenant.id),
        "user_id": str(user.id),
        "transaction_type": "top_up",
        "amount": "500",
        "currency": "ZAR",
        "timestamp": when.isoformat(),
    }


@pytest.mark.asyncio
async def test_campaign_fires_when_inside_window(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Event timestamped inside [start, end] fires the campaign rule."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "camp-in")

    today = datetime.now(UTC).date()
    await _create_campaign_rule(
        async_client,
        test_tenant,
        start=today - timedelta(days=2),
        end=today + timedelta(days=2),
    )

    resp = await async_client.post(
        "/api/v1/events/external",
        json=_event_at(
            tenant=test_tenant,
            user=test_user,
            source_key="camp-in",
            when=datetime.now(UTC),
        ),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["rules_fired"]) == 1


@pytest.mark.asyncio
async def test_campaign_does_not_fire_outside_window(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Event timestamped before the start_date does NOT fire."""
    await _ensure_system_points(db_session, test_tenant)
    await _register_source(async_client, test_tenant, "camp-out")

    # Campaign runs from yesterday onward, but the event is dated 5 days ago.
    await _create_campaign_rule(
        async_client,
        test_tenant,
        start=datetime.now(UTC).date() - timedelta(days=1),
        end=datetime.now(UTC).date() + timedelta(days=30),
    )

    resp = await async_client.post(
        "/api/v1/events/external",
        json=_event_at(
            tenant=test_tenant,
            user=test_user,
            source_key="camp-out",
            when=datetime.now(UTC) - timedelta(days=5),
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["rules_fired"] == []


@pytest.mark.asyncio
async def test_campaign_fires_once_per_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Two qualifying events in the window — only the first fires."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "camp-once")

    today = datetime.now(UTC).date()
    await _create_campaign_rule(
        async_client,
        test_tenant,
        start=today - timedelta(days=1),
        end=today + timedelta(days=7),
    )

    outcomes = []
    for _ in range(2):
        resp = await async_client.post(
            "/api/v1/events/external",
            json=_event_at(
                tenant=test_tenant,
                user=test_user,
                source_key="camp-once",
                when=datetime.now(UTC),
            ),
        )
        outcomes.append(len(resp.json()["rules_fired"]))
    assert outcomes == [1, 0]


@pytest.mark.asyncio
async def test_campaign_requires_both_dates_on_create(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Creating a campaign rule without end_date → 422."""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "bad-camp",
            "rule_type": "campaign",
            "transaction_type": "top_up",
            "campaign_start_date": "2026-06-01",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_campaign_rejects_start_after_end(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """end < start is a config error → 422."""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "inverted-camp",
            "rule_type": "campaign",
            "transaction_type": "top_up",
            "campaign_start_date": "2026-12-31",
            "campaign_end_date": "2026-01-01",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422
