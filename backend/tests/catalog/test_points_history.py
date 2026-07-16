"""Tests for GET /api/v1/catalog/me/points-history (Pay-PRD-0980).

Phase F.4 made the route `/me/` — user_id + tenant_id come from the
session token. Cross-tenant isolation is now structural (a tenant-A session
literally cannot address tenant-B data).
"""

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
    UserIdentifier,
    UserRole,
)
from tests.conftest import create_session_token_for_user, seed_redemption_service_config


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


async def _user_header(user: User) -> dict[str, str]:
    """Mint a Bearer session header for a user."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_points_history_empty_for_user_without_account(
    async_client: AsyncClient,
    test_user: User,
) -> None:
    """User has no points_account → empty array, NOT 404."""
    response = await async_client.get(
        "/api/v1/catalog/me/points-history",
        headers=await _user_header(test_user),
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_points_history_includes_rule_name_for_rewards(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
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
        "/api/v1/catalog/me/points-history",
        headers=await _user_header(test_user),
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
    admin_auth_header: dict[str, str],
    user_points: Account,
    system_points_account: Account,
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

    # Fail-closed gate (invariant #12): seed redemption pricing + limit config.
    await seed_redemption_service_config(db_session, test_tenant)

    # Provider register (admin) + initiate (user).
    pr = await async_client.post(
        "/api/v1/redemption/providers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "P"},
    )
    provider_id = pr.json()["id"]
    user_header = await _user_header(test_user)
    await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**user_header, "Idempotency-Key": uuid4().hex},
        json={
            "provider_id": provider_id,
            "points_amount": "30",
        },
    )

    response = await async_client.get(
        "/api/v1/catalog/me/points-history",
        headers=user_header,
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
    user_points: Account,
    system_points_account: Account,
) -> None:
    """A user in other_tenant cannot see rewards earned in test_tenant.

    Phase F.4 makes this structural — tenant comes from the session, so
    a tenant-B user simply has no rewards in their own tenant's history.
    """
    await _seed_reward(
        db_session,
        test_tenant,
        test_user,
        Decimal("100"),
        rule_name="Tenant A only",
        event_key="evt-xt",
    )

    # A second user in other_tenant — should see nothing.
    other_user = User(tenant_id=other_tenant.id)
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=other_user.id,
            tenant_id=other_tenant.id,
            identifier_type="phone",
            identifier_value="+27 82 555 9000",
            verified=True,
        )
    )
    # Default role for other_tenant lives in `default_user_role_other_tenant`
    # fixture; reproduce inline to keep the test self-contained.
    from app.shared.models import Role, RolePermission

    role = Role(
        tenant_id=other_tenant.id,
        name="standard_user_xt",
        description="cross-tenant test role",
    )
    db_session.add(role)
    await db_session.flush()
    db_session.add(RolePermission(role_id=role.id, transaction_type="p2p", permitted=True))
    db_session.add(UserRole(user_id=other_user.id, role_id=role.id))
    await db_session.commit()

    response = await async_client.get(
        "/api/v1/catalog/me/points-history",
        headers=await _user_header(other_user),
    )
    assert response.status_code == 200
    assert response.json() == []
