"""Tests for GET /api/v1/catalog/{user_id}/points-history (Pay-PRD-0980)."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    Account,
    Rule,
    Tenant,
    User,
)


async def _seed_reward(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    amount: Decimal,
    *,
    rule_name: str,
    event_key: str,
) -> Rule:
    """Helper — issue points to the user from a named rule."""
    rule = Rule(
        tenant_id=tenant.id,
        name=rule_name,
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=amount,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        rule=rule,
        triggering_event_id=event_key,
        reward_value=amount,
    )
    return rule


@pytest.mark.asyncio
async def test_points_history_empty_for_user_without_account(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """User has no points_account → empty array, NOT 404."""
    response = await async_client.get(
        f"/api/v1/catalog/{test_user.id}/points-history",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_points_history_includes_rule_name_for_rewards(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001 — ensures points account exists
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Reward-issuance entries surface the firing rule's name."""
    await _seed_reward(
        db_session,
        test_tenant,
        test_user,
        Decimal("75"),
        rule_name="Welcome bonus",
        event_key="evt-welcome",
    )

    response = await async_client.get(
        f"/api/v1/catalog/{test_user.id}/points-history",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    entry = items[0]
    assert entry["direction"] == "CREDIT"
    assert Decimal(entry["amount"]) == Decimal("75")
    assert entry["status"] == "COMPLETED"
    assert entry["transaction_type"] == "reward_issuance"
    assert entry["rule_name"] == "Welcome bonus"
    assert entry["triggering_event_id"] == "evt-welcome"


@pytest.mark.asyncio
async def test_points_history_orders_newest_first(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Two rewards then a redemption → 3 entries, newest first."""
    await _seed_reward(
        db_session,
        test_tenant,
        test_user,
        Decimal("100"),
        rule_name="First",
        event_key="evt-1",
    )
    await _seed_reward(
        db_session,
        test_tenant,
        test_user,
        Decimal("50"),
        rule_name="Second",
        event_key="evt-2",
    )

    # Initiate a redemption (DEBIT 30 PENDING).
    pr = await async_client.post(
        "/api/v1/redemption/providers",
        json={"tenant_id": str(test_tenant.id), "name": "P"},
    )
    provider_id = pr.json()["id"]
    await async_client.post(
        "/api/v1/redemption/initiate",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "provider_id": provider_id,
            "points_amount": "30",
        },
    )

    response = await async_client.get(
        f"/api/v1/catalog/{test_user.id}/points-history",
        params={"tenant_id": str(test_tenant.id)},
    )
    items = response.json()
    # 3 entries on the user's points_account: 2 CREDIT (rewards) + 1 DEBIT (redemption).
    assert len(items) == 3

    # Newest first — the redemption DEBIT happened last.
    assert items[0]["transaction_type"] == "redemption"
    assert items[0]["direction"] == "DEBIT"
    assert items[0]["status"] == "PENDING"

    # Followed by the second reward, then the first.
    assert items[1]["rule_name"] == "Second"
    assert items[2]["rule_name"] == "First"


@pytest.mark.asyncio
async def test_points_history_cross_tenant_isolated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Querying the user's history under a different tenant returns []."""
    await _seed_reward(
        db_session,
        test_tenant,
        test_user,
        Decimal("100"),
        rule_name="Tenant A only",
        event_key="evt-xt",
    )

    # test_user belongs to test_tenant; ask other_tenant for their history.
    response = await async_client.get(
        f"/api/v1/catalog/{test_user.id}/points-history",
        params={"tenant_id": str(other_tenant.id)},
    )
    assert response.status_code == 200
    assert response.json() == []
