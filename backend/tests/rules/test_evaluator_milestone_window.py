"""Milestone time-window enforcement (Pay-PRD-0550).

A milestone rule counts qualifying events only inside its `time_window`
(lifetime / calendar_month / rolling_7d) — events outside the window must
not contribute to the count. Drives the engine through the INTERNAL
wallet-outbox path (`evaluate_and_issue_firings`) like the value-based
tests, because `test_tenant` is a `both`-mode tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Tenant,
    User,
)


async def _ensure_points_accounts(session: AsyncSession, tenant: Tenant, user: User) -> None:
    """Create the tenant's system points master + the user's points account."""
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
    session.add(
        Account(
            tenant_id=tenant.id,
            user_id=user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    await session.commit()


async def _create_milestone_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    count_threshold: int,
    time_window: str | None,
) -> None:
    """Create a milestone rule via the public API."""
    body = {
        "tenant_id": str(tenant.id),
        "name": f"milestone-{uuid4().hex[:6]}",
        "rule_type": "milestone",
        "transaction_type": "fund",
        "count_threshold": count_threshold,
        "reward_type": "points",
        "reward_value": "50",
    }
    if time_window is not None:
        body["time_window"] = time_window
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text


async def _ingest_at(session: AsyncSession, tenant: Tenant, user: User, *, at: datetime) -> int:
    """Drive one qualifying wallet event at an explicit timestamp; return firings."""
    event = NormalisedEvent(
        event_id=uuid4().hex,
        source_key="internal:wallet",
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="fund",
        amount=Decimal("500"),
        currency="ZAR",
        merchant_id=None,
        timestamp=at,
    )
    firings = await evaluate_and_issue_firings(session, event)
    return len(firings)


@pytest.mark.asyncio
async def test_milestone_rolling_7d_excludes_events_outside_window(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a rolling-7d milestone does not count an event older than the window"""
    await _ensure_points_accounts(db_session, test_tenant, test_user)
    await _create_milestone_rule(
        async_client, test_tenant, count_threshold=2, time_window="rolling_7d"
    )

    t0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    t_outside = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)  # 8 days later — t0 aged out
    t_inside = datetime(2026, 6, 9, 13, 0, tzinfo=UTC)  # 1h after — same window

    assert await _ingest_at(db_session, test_tenant, test_user, at=t0) == 0
    assert await _ingest_at(db_session, test_tenant, test_user, at=t_outside) == 0
    assert await _ingest_at(db_session, test_tenant, test_user, at=t_inside) == 1


@pytest.mark.asyncio
async def test_milestone_calendar_month_resets_counter_each_month(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a calendar-month milestone starts a fresh count in a new month"""
    await _ensure_points_accounts(db_session, test_tenant, test_user)
    await _create_milestone_rule(
        async_client, test_tenant, count_threshold=2, time_window="calendar_month"
    )

    jan_31 = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
    feb_1 = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    feb_2 = datetime(2026, 2, 2, 12, 0, tzinfo=UTC)

    assert await _ingest_at(db_session, test_tenant, test_user, at=jan_31) == 0
    # New month → January's event no longer counts.
    assert await _ingest_at(db_session, test_tenant, test_user, at=feb_1) == 0
    assert await _ingest_at(db_session, test_tenant, test_user, at=feb_2) == 1


@pytest.mark.asyncio
async def test_milestone_lifetime_counts_across_months(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a lifetime milestone accumulates its count with no expiry"""
    await _ensure_points_accounts(db_session, test_tenant, test_user)
    await _create_milestone_rule(
        async_client, test_tenant, count_threshold=2, time_window="lifetime"
    )

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t1 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)  # two months later still counts

    assert await _ingest_at(db_session, test_tenant, test_user, at=t0) == 0
    assert await _ingest_at(db_session, test_tenant, test_user, at=t1) == 1
