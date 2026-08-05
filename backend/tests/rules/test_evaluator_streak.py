"""Streak rewards.

Streak rules track `current_streak` on UserRuleProgress: increments on a
qualifying event in the immediately-next period (day/week), resets on a
gap > 1 period, and is a no-op when two events land in the same period.

Driven through the INTERNAL wallet-outbox path — a direct
`evaluate_and_issue_firings` call shaped like `reward_outbox` rows
(`source_key="internal:wallet"`, explicit per-event timestamp) — because
`test_tenant` is a `both`-mode tenant, where rewards come from the wallet
outbox and external HTTP ingest is correctly rejected (`wrong_mode`). The
explicit timestamp per event is exactly why the direct call is used: it lets
each test place events on chosen calendar days/weeks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
        "transaction_type": "fund",
        "streak_units": units,
        "streak_unit_window": window,
        "resets_after_trigger": resets_after_trigger,
        "reward_type": "points",
        "reward_value": reward_value,
    }
    resp = await client.post("/api/v1/rules", json=body)
    assert resp.status_code == 201, resp.text


async def _ingest(session: AsyncSession, tenant: Tenant, user: User, when: datetime) -> int:
    """Drive one internal wallet event at `when`; return the number of firings.

    Mirrors how `reward_outbox` shapes an event for `evaluate_and_issue_firings`:
    an `internal:wallet` source, a per-transaction event_id, and an explicit
    timestamp (which the streak evaluator reads to place the event in a period).
    """
    event = NormalisedEvent(
        event_id=uuid4().hex,
        source_key="internal:wallet",
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="fund",
        amount=Decimal("500"),
        currency="ZAR",
        merchant_id=None,
        timestamp=when,
    )
    firings = await evaluate_and_issue_firings(session, event)
    return len(firings)


@pytest.mark.asyncio
async def test_streak_fires_on_n_consecutive_days(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer earns a streak reward after several consecutive days of activity"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _create_streak_rule(async_client, test_tenant, units=3, window="day")

    base = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    outcomes = [
        await _ingest(db_session, test_tenant, test_user, base),
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=1)),
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=2)),
    ]
    assert outcomes == [0, 0, 1]


@pytest.mark.asyncio
async def test_streak_breaks_on_gap_and_restarts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer's streak resets when they miss a day"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _create_streak_rule(async_client, test_tenant, units=3, window="day")

    base = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    outcomes = [
        await _ingest(db_session, test_tenant, test_user, base),
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=1)),
        # gap — skip day 3.
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=3)),
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=4)),
    ]
    assert outcomes == [0, 0, 0, 0]


@pytest.mark.asyncio
async def test_streak_same_day_is_no_op(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify multiple actions on the same day advance a streak only once"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _create_streak_rule(async_client, test_tenant, units=2, window="day")

    base = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    outcomes = [
        # Two events same day — should NOT fire the 2-day streak.
        await _ingest(db_session, test_tenant, test_user, base),
        await _ingest(db_session, test_tenant, test_user, base + timedelta(hours=4)),
        # Day 2 — NOW fire.
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=1)),
    ]
    assert outcomes == [0, 0, 1]


@pytest.mark.asyncio
async def test_streak_resets_after_trigger(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer can earn a streak reward again after it resets"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _create_streak_rule(
        async_client, test_tenant, units=3, window="day", resets_after_trigger=True
    )

    base = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    outcomes = []
    for offset in range(6):
        outcomes.append(
            await _ingest(db_session, test_tenant, test_user, base + timedelta(days=offset))
        )
    # Days 1,2 → 0, Day 3 → 1, then resets. Days 4,5 → 0, Day 6 → 1.
    assert outcomes == [0, 0, 1, 0, 0, 1]


@pytest.mark.asyncio
async def test_streak_requires_units_and_window_on_create(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a streak rule is rejected when its length is missing"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "bad-streak",
            "rule_type": "streak",
            "transaction_type": "fund",
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
    """Verify a customer's streak count grows with each qualifying day"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)
    await _create_streak_rule(async_client, test_tenant, units=5, window="day")

    base = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    for offset in range(3):
        await _ingest(db_session, test_tenant, test_user, base + timedelta(days=offset))

    progress = (
        await db_session.execute(
            select(UserRuleProgress).where(UserRuleProgress.user_id == test_user.id)
        )
    ).scalar_one()
    assert progress.current_streak == 3
