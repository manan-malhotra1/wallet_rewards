"""My rewards — the signed-in user's rule catalog + recent reward firings.

`GET /api/v1/identity/me/rewards` returns the tenant's active rule catalog (each
with the caller's progress + status) and the caller's latest reward events. A
`wallet`-mode tenant has no rewards engine, so it returns `enabled=False` with
empty lists. `POST /api/v1/identity/me/rewards/seen` acknowledges the caller's
own reward_events (user-scoped, idempotent).

Covers:
  - wallet-mode tenant → enabled False, empty catalog/recent.
  - both-mode tenant → milestone rule shows current/target/label + in_progress.
  - 401 without a session token.
  - tenant isolation — only the caller's own tenant's rules + own reward events.
  - mark-seen flips the flag and is idempotent (second call marks 0).
  - mark-seen is user-scoped — a user cannot mark another user's rewards.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    RewardEvent,
    Rule,
    Tenant,
    User,
    UserRuleProgress,
)
from tests.conftest import create_session_token_for_user


async def _seed_milestone_rule(
    session: AsyncSession,
    tenant_id,
    *,
    transaction_type: str = "p2p",
    count_threshold: int = 3,
    name: str = "3 P2P transfers",
) -> Rule:
    """Seed an ACTIVE points milestone rule for the tenant."""
    rule = Rule(
        tenant_id=tenant_id,
        name=name,
        description="Send 3 P2P transfers to earn points.",
        rule_type="milestone",
        transaction_type=transaction_type,
        count_threshold=count_threshold,
        reward_type="points",
        reward_value=Decimal("50"),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def _seed_reward_event(
    session: AsyncSession, *, user_id, rule_id, seen: bool = False
) -> RewardEvent:
    """Seed a single points reward_event for a user (unseen by default)."""
    event = RewardEvent(
        user_id=user_id,
        rule_id=rule_id,
        triggering_event_id=uuid4().hex,
        reward_type="points",
        reward_value=Decimal("50"),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


@pytest.mark.asyncio
async def test_me_rewards_disabled_for_wallet_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant_factory,
    user_factory,
) -> None:
    """Verify a wallet-only tenant's user sees rewards disabled with nothing to show."""
    tenant = await tenant_factory(business_type="wallet")
    user = await user_factory(tenant)
    token = await create_session_token_for_user(user.id, tenant.id)

    response = await async_client.get(
        "/api/v1/identity/me/rewards", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["catalog"] == []
    assert body["recent"] == []


@pytest.mark.asyncio
async def test_me_rewards_shows_progress_for_both_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a user sees a milestone rule's current-of-target progress and status."""
    rule = await _seed_milestone_rule(db_session, test_tenant.id)
    # One unit of progress toward the target of 3.
    db_session.add(
        UserRuleProgress(user_id=test_user.id, rule_id=rule.id, current_count=1)
    )
    await db_session.commit()

    response = await async_client.get(
        "/api/v1/identity/me/rewards", headers=alice_auth_header
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert len(body["catalog"]) == 1
    item = body["catalog"][0]
    assert item["reward_type"] == "points"
    assert item["currency"] == "PTS"
    assert item["status"] == "in_progress"
    assert item["progress"] == {"current": 1, "target": 3, "label": "P2P transfers"}


@pytest.mark.asyncio
async def test_me_rewards_requires_auth(async_client: AsyncClient) -> None:
    """Verify viewing rewards requires signing in."""
    response = await async_client.get("/api/v1/identity/me/rewards")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rewards_tenant_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a user sees only their own tenant's rules and their own reward events."""
    own_rule = await _seed_milestone_rule(db_session, test_tenant.id, name="own-rule")
    # A rule + a reward event belonging entirely to ANOTHER tenant / user.
    other_rule = await _seed_milestone_rule(db_session, other_tenant.id, name="other-rule")
    other_user = User(tenant_id=other_tenant.id)
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)
    await _seed_reward_event(db_session, user_id=other_user.id, rule_id=other_rule.id)

    response = await async_client.get(
        "/api/v1/identity/me/rewards", headers=alice_auth_header
    )
    assert response.status_code == 200, response.text
    body = response.json()
    catalog_ids = {item["rule_id"] for item in body["catalog"]}
    assert catalog_ids == {str(own_rule.id)}
    assert body["recent"] == []


@pytest.mark.asyncio
async def test_mark_rewards_seen_flips_flag(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify marking a reward seen flips its flag and repeating the call is a no-op."""
    rule = await _seed_milestone_rule(db_session, test_tenant.id)
    event = await _seed_reward_event(db_session, user_id=test_user.id, rule_id=rule.id)

    response = await async_client.post(
        "/api/v1/identity/me/rewards/seen",
        headers=alice_auth_header,
        json={"reward_event_ids": [str(event.id)]},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"marked": 1}

    # The recent feed now reports the reward as seen.
    feed = await async_client.get("/api/v1/identity/me/rewards", headers=alice_auth_header)
    recent = feed.json()["recent"]
    assert len(recent) == 1
    assert recent[0]["reward_event_id"] == str(event.id)
    assert recent[0]["seen"] is True

    # Idempotent — a second identical POST marks nothing.
    again = await async_client.post(
        "/api/v1/identity/me/rewards/seen",
        headers=alice_auth_header,
        json={"reward_event_ids": [str(event.id)]},
    )
    assert again.status_code == 200
    assert again.json() == {"marked": 0}


@pytest.mark.asyncio
async def test_mark_rewards_seen_is_user_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a user cannot mark another user's reward event seen."""
    rule = await _seed_milestone_rule(db_session, test_tenant.id)
    # User B in the same tenant owns the reward event.
    user_b = User(tenant_id=test_tenant.id)
    db_session.add(user_b)
    await db_session.commit()
    await db_session.refresh(user_b)
    event_b = await _seed_reward_event(db_session, user_id=user_b.id, rule_id=rule.id)

    # Alice (test_user) tries to mark B's event.
    response = await async_client.post(
        "/api/v1/identity/me/rewards/seen",
        headers=alice_auth_header,
        json={"reward_event_ids": [str(event_b.id)]},
    )
    assert response.status_code == 200
    assert response.json() == {"marked": 0}

    # B's row is untouched.
    row = (
        await db_session.execute(select(RewardEvent).where(RewardEvent.id == event_b.id))
    ).scalar_one()
    await db_session.refresh(row)
    assert row.seen_at is None
