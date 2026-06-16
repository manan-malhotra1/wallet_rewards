"""Tests for GET /api/v1/rules/{rule_id}/performance (campaign metrics).

Covers:
  - Happy path: empty rule returns zeros + null timestamps
  - Happy path: rule with N fires across M users returns those counts
  - 404 on unknown rule_id
  - 404 on cross-tenant access (no metric leak)
  - 401 / 403 are inherited from the admin auth dependency — covered
    by the existing rules router auth tests, not re-asserted here.

Uses the same fixtures as the rest of the rules suite. Reward events
are seeded directly via the ORM — no need to go through the rule
evaluator, which would couple this to Module 9.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import RewardEvent, Rule, Tenant, User


async def _create_rule(client: AsyncClient, tenant_id: str, name: str) -> str:
    """Helper — create a first_time rule and return its id."""
    response = await client.post(
        "/api/v1/rules",
        json={
            "tenant_id": tenant_id,
            "name": name,
            "rule_type": "first_time",
            "transaction_type": "top_up",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _seed_reward_events(
    db_session: AsyncSession,
    *,
    rule_id: str,
    fires: list[tuple[User, Decimal]],
) -> None:
    """Insert `RewardEvent` rows directly. Each tuple is (user, value)."""
    for i, (user, value) in enumerate(fires):
        db_session.add(
            RewardEvent(
                user_id=user.id,
                rule_id=rule_id,
                triggering_event_id=f"evt-{i}-{uuid4().hex}",
                reward_type="points",
                reward_value=value,
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_performance_empty_rule_returns_zeros(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """A rule that has never fired returns total=0, unique=0, null timestamps."""
    rule_id = await _create_rule(async_client, str(test_tenant.id), "Empty rule")

    response = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rule_id"] == rule_id
    assert body["total_fires"] == 0
    assert body["unique_users_rewarded"] == 0
    assert Decimal(body["total_reward_value"]) == Decimal("0")
    assert body["first_fired_at"] is None
    assert body["last_fired_at"] is None


@pytest.mark.asyncio
async def test_performance_counts_fires_and_unique_users(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """5 fires across 2 distinct users → total=5, unique=2, sum is right."""
    rule_id = await _create_rule(async_client, str(test_tenant.id), "Active rule")

    # Create a second user inline — the suite has no secondary-user fixture
    # and going through the API would couple this to identity-create payloads.
    second_user = User(tenant_id=test_tenant.id)
    db_session.add(second_user)
    await db_session.commit()
    await db_session.refresh(second_user)

    # 3 fires from user A, 2 from user B → total 5, unique 2.
    await _seed_reward_events(
        db_session,
        rule_id=rule_id,
        fires=[
            (test_user, Decimal("100")),
            (test_user, Decimal("100")),
            (test_user, Decimal("100")),
            (second_user, Decimal("100")),
            (second_user, Decimal("100")),
        ],
    )

    response = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_fires"] == 5
    assert body["unique_users_rewarded"] == 2
    assert Decimal(body["total_reward_value"]) == Decimal("500")
    assert body["first_fired_at"] is not None
    assert body["last_fired_at"] is not None


@pytest.mark.asyncio
async def test_performance_unknown_rule_returns_404(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Unknown rule_id → 404 with rule_not_found error code."""
    response = await async_client.get(
        f"/api/v1/rules/{uuid4()}/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "rule_not_found"


@pytest.mark.asyncio
async def test_performance_cross_tenant_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Tenant B requesting Tenant A's rule gets 404 (no existence leak)."""
    rule_id = await _create_rule(async_client, str(test_tenant.id), "Tenant A rule")

    response = await async_client.get(
        f"/api/v1/rules/{rule_id}/performance",
        params={"tenant_id": str(other_tenant.id)},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "rule_not_found"


@pytest.mark.asyncio
async def test_performance_malformed_rule_id_returns_422(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """A non-UUID `rule_id` path param is rejected at parse time (422)."""
    response = await async_client.get(
        "/api/v1/rules/not-a-uuid/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 422
