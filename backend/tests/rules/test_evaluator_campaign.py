"""Campaign rewards.

Campaign rules fire once per user, only within
[campaign_start_date, campaign_end_date]. Outside the window the rule
is a no-op.

Driven through the INTERNAL wallet-outbox path — a direct
`evaluate_and_issue_firings` call shaped like `reward_outbox` rows
(`source_key="internal:wallet"`, explicit per-event timestamp) — because
`test_tenant` is a `both`-mode tenant, where rewards come from the wallet
outbox and external HTTP ingest is correctly rejected (`wrong_mode`). The
explicit timestamp lets each test place the event inside or outside the
campaign window.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


async def _create_campaign_rule(
    client: AsyncClient,
    tenant: Tenant,
    *,
    start: date,
    end: date,
    transaction_type: str = "fund",
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


async def _ingest(session: AsyncSession, tenant: Tenant, user: User, when: datetime) -> int:
    """Drive one internal wallet event at `when`; return the number of firings.

    Mirrors how `reward_outbox` shapes an event for `evaluate_and_issue_firings`:
    an `internal:wallet` source, a per-transaction event_id, and an explicit
    timestamp (which the campaign evaluator gates against the date window).
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
async def test_campaign_fires_when_inside_window(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer earns a campaign reward during the campaign period"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)

    today = datetime.now(UTC).date()
    await _create_campaign_rule(
        async_client,
        test_tenant,
        start=today - timedelta(days=2),
        end=today + timedelta(days=2),
    )

    assert await _ingest(db_session, test_tenant, test_user, datetime.now(UTC)) == 1


@pytest.mark.asyncio
async def test_campaign_does_not_fire_outside_window(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer earns no campaign reward before the campaign starts"""
    await _ensure_system_points(db_session, test_tenant)

    # Campaign runs from yesterday onward, but the event is dated 5 days ago.
    await _create_campaign_rule(
        async_client,
        test_tenant,
        start=datetime.now(UTC).date() - timedelta(days=1),
        end=datetime.now(UTC).date() + timedelta(days=30),
    )

    assert (
        await _ingest(db_session, test_tenant, test_user, datetime.now(UTC) - timedelta(days=5))
        == 0
    )


@pytest.mark.asyncio
async def test_campaign_fires_once_per_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer earns a campaign reward only once"""
    await _ensure_system_points(db_session, test_tenant)
    await _user_points_account(db_session, test_tenant, test_user)

    today = datetime.now(UTC).date()
    await _create_campaign_rule(
        async_client,
        test_tenant,
        start=today - timedelta(days=1),
        end=today + timedelta(days=7),
    )

    outcomes = [
        await _ingest(db_session, test_tenant, test_user, datetime.now(UTC)) for _ in range(2)
    ]
    assert outcomes == [1, 0]


@pytest.mark.asyncio
async def test_campaign_requires_both_dates_on_create(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a campaign rule is rejected when its end date is missing"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "bad-camp",
            "rule_type": "campaign",
            "transaction_type": "fund",
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
    """Verify a campaign rule is rejected when it ends before it starts"""
    resp = await async_client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(test_tenant.id),
            "name": "inverted-camp",
            "rule_type": "campaign",
            "transaction_type": "fund",
            "campaign_start_date": "2026-12-31",
            "campaign_end_date": "2026-01-01",
            "reward_type": "points",
            "reward_value": "50",
        },
    )
    assert resp.status_code == 422
