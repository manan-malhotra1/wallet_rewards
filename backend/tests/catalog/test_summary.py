"""Tests for GET /api/v1/catalog/me/summary + redemption-history.

Phase F.4: catalog endpoints are user-only. tenant_id + user_id come from
the session token — there is no longer a `/{user_id}/` path. Provider
register + redemption confirm in setup helpers stay admin-only.
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
)
from tests.conftest import create_session_token_for_user, seed_redemption_service_config


async def _seed_reward(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    amount: Decimal,
    *,
    key: str,
) -> None:
    """Helper — issue some points to the user."""
    rule = Rule(
        tenant_id=tenant.id,
        name=f"rule-{key}",
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
        triggering_event_id=key,
        reward_value=amount,
    )


async def _user_header(user: User) -> dict[str, str]:
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_summary_for_user_with_no_points_account(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """User with no points_account → response with points: null."""
    response = await async_client.get(
        "/api/v1/catalog/me/summary",
        headers=await _user_header(test_user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["points"] is None


@pytest.mark.asyncio
async def test_summary_reflects_lifetime_earned(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """After two reward issuances: available + lifetime_earned both = sum."""
    await _seed_reward(db_session, test_tenant, test_user, Decimal("100"), key="a")
    await _seed_reward(db_session, test_tenant, test_user, Decimal("50"), key="b")

    response = await async_client.get(
        "/api/v1/catalog/me/summary",
        headers=await _user_header(test_user),
    )
    assert response.status_code == 200
    points = response.json()["points"]
    assert Decimal(points["available"]) == Decimal("150")
    assert Decimal(points["lifetime_earned"]) == Decimal("150")
    assert Decimal(points["lifetime_redeemed"]) == Decimal("0")


@pytest.mark.asyncio
async def test_summary_reflects_lifetime_redeemed(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    user_points: Account,
    system_points_account: Account,
) -> None:
    """After redeem + confirm, lifetime_redeemed reflects the COMPLETED debit.

    Mixes auth contexts: admin for provider + confirm, user for initiate +
    catalog read.
    """
    await _seed_reward(db_session, test_tenant, test_user, Decimal("200"), key="r1")

    await seed_redemption_service_config(db_session, test_tenant)
    pr = await async_client.post(
        "/api/v1/redemption/providers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "P"},
    )
    provider_id = pr.json()["id"]

    user_header = await _user_header(test_user)
    init = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**user_header, "Idempotency-Key": uuid4().hex},
        json={
            "provider_id": provider_id,
            "points_amount": "80",
        },
    )
    redemption_id = init.json()["id"]
    await async_client.post(
        f"/api/v1/redemption/{redemption_id}/confirm",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id)},
    )

    response = await async_client.get(
        "/api/v1/catalog/me/summary",
        headers=user_header,
    )
    points = response.json()["points"]
    assert Decimal(points["available"]) == Decimal("120")
    assert Decimal(points["lifetime_earned"]) == Decimal("200")
    assert Decimal(points["lifetime_redeemed"]) == Decimal("80")


@pytest.mark.asyncio
async def test_redemption_history_returns_user_redemptions(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Redemption history is newest-first and tenant-scoped via session."""
    await _seed_reward(db_session, test_tenant, test_user, Decimal("100"), key="h")
    await seed_redemption_service_config(db_session, test_tenant)
    pr = await async_client.post(
        "/api/v1/redemption/providers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "P"},
    )
    provider_id = pr.json()["id"]

    user_header = await _user_header(test_user)
    # Two redemptions.
    for amount in ("10", "20"):
        await async_client.post(
            "/api/v1/redemption/initiate",
            headers={**user_header, "Idempotency-Key": uuid4().hex},
            json={
                "provider_id": provider_id,
                "points_amount": amount,
            },
        )

    response = await async_client.get(
        "/api/v1/catalog/me/redemption-history",
        headers=user_header,
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    # Newest first.
    assert Decimal(items[0]["points_amount"]) == Decimal("20")
    assert Decimal(items[1]["points_amount"]) == Decimal("10")
