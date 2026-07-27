"""Reward rule performance.

Covers:
  - Per-rule GET /api/v1/rules/{rule_id}/performance:
      happy path empty / non-empty, 404 unknown / cross-tenant, 422 malformed UUID.
  - Batch GET /api/v1/rules/performance:
      happy path with mixed fire counts, zero-fire rules included via LEFT JOIN,
      tenant isolation, empty tenant returns [].
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

from app.shared.models import RewardEvent, Tenant, User


async def _create_rule(client: AsyncClient, tenant_id: str, name: str) -> str:
    """Helper — create a first_time rule and return its id."""
    response = await client.post(
        "/api/v1/rules",
        json={
            "tenant_id": tenant_id,
            "name": name,
            "rule_type": "first_time",
            "transaction_type": "fund",
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
    """Verify a rule that has never rewarded anyone shows zero activity"""
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
    """Verify a rule's performance shows how many rewards and distinct customers it reached"""
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
    """Verify performance for an unknown rule is not found"""
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
    """Verify a business cannot view another business's rule performance"""
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
    """Verify a badly formed rule reference is rejected"""
    response = await async_client.get(
        "/api/v1/rules/not-a-uuid/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 422


# -- Batch endpoint -----------------------------------------------------------
# GET /api/v1/rules/performance returns one row per rule in the tenant in a
# single SQL round-trip. The campaigns list page calls this instead of the
# per-rule endpoint to avoid an N+1 once tenants scale past ~100 rules.


@pytest.mark.asyncio
async def test_list_performance_aggregates_every_rule_in_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify the performance overview reports every rule including those that never fired"""
    busy_rule = await _create_rule(async_client, str(test_tenant.id), "Busy")
    quiet_rule = await _create_rule(async_client, str(test_tenant.id), "Quiet")
    silent_rule = await _create_rule(async_client, str(test_tenant.id), "Silent")

    second_user = User(tenant_id=test_tenant.id)
    db_session.add(second_user)
    await db_session.commit()
    await db_session.refresh(second_user)

    # busy_rule: 3 fires, 2 users, 600 total.
    await _seed_reward_events(
        db_session,
        rule_id=busy_rule,
        fires=[
            (test_user, Decimal("100")),
            (test_user, Decimal("200")),
            (second_user, Decimal("300")),
        ],
    )
    # quiet_rule: 1 fire, 1 user, 50 total.
    await _seed_reward_events(
        db_session,
        rule_id=quiet_rule,
        fires=[(test_user, Decimal("50"))],
    )
    # silent_rule: no events → must still appear with zeros.

    response = await async_client.get(
        "/api/v1/rules/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    rows = {row["rule_id"]: row for row in response.json()}

    assert set(rows) == {busy_rule, quiet_rule, silent_rule}

    assert rows[busy_rule]["total_fires"] == 3
    assert rows[busy_rule]["unique_users_rewarded"] == 2
    assert Decimal(rows[busy_rule]["total_reward_value"]) == Decimal("600")
    assert rows[busy_rule]["first_fired_at"] is not None
    assert rows[busy_rule]["last_fired_at"] is not None

    assert rows[quiet_rule]["total_fires"] == 1
    assert rows[quiet_rule]["unique_users_rewarded"] == 1
    assert Decimal(rows[quiet_rule]["total_reward_value"]) == Decimal("50")

    assert rows[silent_rule]["total_fires"] == 0
    assert rows[silent_rule]["unique_users_rewarded"] == 0
    assert Decimal(rows[silent_rule]["total_reward_value"]) == Decimal("0")
    assert rows[silent_rule]["first_fired_at"] is None
    assert rows[silent_rule]["last_fired_at"] is None


@pytest.mark.asyncio
async def test_list_performance_isolates_by_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Verify a business's performance overview excludes other businesses' rules"""
    a_rule = await _create_rule(async_client, str(test_tenant.id), "A-only")
    b_rule = await _create_rule(async_client, str(other_tenant.id), "B-only")

    response = await async_client.get(
        "/api/v1/rules/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    rule_ids = {row["rule_id"] for row in response.json()}
    assert a_rule in rule_ids
    assert b_rule not in rule_ids


@pytest.mark.asyncio
async def test_list_performance_empty_tenant_returns_empty_list(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify a business with no rules gets an empty performance overview"""
    response = await async_client.get(
        "/api/v1/rules/performance",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    assert response.json() == []
