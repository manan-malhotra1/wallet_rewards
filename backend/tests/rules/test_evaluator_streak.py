"""Tests for the streak rule type — Epic 10 (WAL-73).

Streak rules track `current_streak` on UserRuleProgress: increments on a
qualifying event in the immediately-next period (day/week), resets on a
gap > 1 period, and is a no-op when two events land in the same period.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    UserRuleProgress,
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
    """Create a points account for the user."""
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


async def _create_streak_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    units: int,
    window: str = "day",
    reward_value: str = "200",
    resets_after_trigger: bool = True,
) -> None:
    """Create a streak rule via the API."""
    body = {
        "tenant_id": str(tenant.id),
        "name": f"streak-{uuid4().hex[:6]}",
        "rule_type": "streak",
        "transaction_type": "top_up",
        "streak_units": units,
        "streak_unit_window": window,
        "resets_after_trigger": resets_after_trigger,
        "reward_type": "points",
        "reward_value": reward_value,
    }
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text


def _event_at(*, tenant: Tenant, user: User, source_key: str, when: datetime) -> dict:
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


async def _ingest(
    client: AsyncClient, tenant: Tenant, user: User, source_key: str, when: datetime
) -> int:
    """Send one event; return the number of rules fired."""
    resp = await client.post(
        "/api/v1/events/external",
        json=_event_at(tenant=tenant, user=user, source_key=source_key, when=when),
    )
    return len(resp.json()["rules_fired"])


@pytest.mark.asyncio
async def test_streak_fires_on_n_consecutive_days(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """3-day streak: event on day 1, 2, 3 → day 3 fires."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "streak-3d")
    await _create_streak_rule(async_client, test_tenant, units=3, window="day")

    base = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    outcomes = [
        await _ingest(async_client, test_tenant, test_user, "streak-3d", base),
        await _ingest(async_client, test_tenant, test_user, "streak-3d", base + timedelta(days=1)),
        await _ingest(async_client, test_tenant, test_user, "streak-3d", base + timedelta(days=2)),
    ]
    assert outcomes == [0, 0, 1]


@pytest.mark.asyncio
async def test_streak_breaks_on_gap_and_restarts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Day 1 → 2 → 4 (gap) → 5. Streak resets at day 4; never reaches 3."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "streak-break")
    await _create_streak_rule(async_client, test_tenant, units=3, window="day")

    base = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    outcomes = [
        await _ingest(async_client, test_tenant, test_user, "streak-break", base),
        await _ingest(
            async_client, test_tenant, test_user, "streak-break", base + timedelta(days=1)
        ),
        # gap — skip day 3.
        await _ingest(
            async_client, test_tenant, test_user, "streak-break", base + timedelta(days=3)
        ),
        await _ingest(
            async_client, test_tenant, test_user, "streak-break", base + timedelta(days=4)
        ),
    ]
    assert outcomes == [0, 0, 0, 0]


@pytest.mark.asyncio
async def test_streak_same_day_is_no_op(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Two events on day 1 should advance the streak by 1, not 2."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "streak-same-day")
    await _create_streak_rule(async_client, test_tenant, units=2, window="day")

    base = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    outcomes = [
        # Two events same day — should NOT fire the 2-day streak.
        await _ingest(async_client, test_tenant, test_user, "streak-same-day", base),
        await _ingest(
            async_client,
            test_tenant,
            test_user,
            "streak-same-day",
            base + timedelta(hours=4),
        ),
        # Day 2 — NOW fire.
        await _ingest(
            async_client,
            test_tenant,
            test_user,
            "streak-same-day",
            base + timedelta(days=1),
        ),
    ]
    assert outcomes == [0, 0, 1]


@pytest.mark.asyncio
async def test_streak_resets_after_trigger(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """After firing on day 3, the streak resets and fires again on day 6."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "streak-reset")
    await _create_streak_rule(
        async_client, test_tenant, units=3, window="day", resets_after_trigger=True
    )

    base = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    outcomes = []
    for offset in range(6):
        outcomes.append(
            await _ingest(
                async_client,
                test_tenant,
                test_user,
                "streak-reset",
                base + timedelta(days=offset),
            )
        )
    # Days 1,2 → 0, Day 3 → 1, then resets. Days 4,5 → 0, Day 6 → 1.
    assert outcomes == [0, 0, 1, 0, 0, 1]


@pytest.mark.asyncio
async def test_streak_requires_units_and_window_on_create(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Missing streak_units → 422."""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "bad-streak",
            "rule_type": "streak",
            "transaction_type": "top_up",
            # streak_units intentionally omitted
            "streak_unit_window": "day",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_streak_progress_state_increments(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """current_streak on user_rule_progress increments per qualifying day."""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _register_source(async_client, test_tenant, "streak-state")
    await _create_streak_rule(async_client, test_tenant, units=5, window="day")

    base = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    for offset in range(3):
        await _ingest(
            async_client,
            test_tenant,
            test_user,
            "streak-state",
            base + timedelta(days=offset),
        )

    progress = (
        await db_session.execute(
            select(UserRuleProgress).where(UserRuleProgress.user_id == test_user.id)
        )
    ).scalar_one()
    assert progress.current_streak == 3
