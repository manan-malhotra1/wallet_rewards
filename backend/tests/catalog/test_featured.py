"""Featured campaign card — the reward the mobile home screen highlights.

Covers happy path, empty/inactive/out-of-window paths, tenant isolation,
and the 401 auth-failure case. Campaign rules are seeded directly via
SQLAlchemy — the rules-engine admin endpoint requires a richer payload
than the catalog read-side needs to exercise.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Rule, Tenant, User
from tests.conftest import create_session_token_for_user


async def _seed_campaign(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    name: str = "Spring Bonus",
    description: str | None = "Earn extra points on every fund",
    status: str = "active",
    reward_value: Decimal = Decimal("100"),
    start: date | None = None,
    end: date | None = None,
) -> Rule:
    """Seed a campaign-type rule and commit so the endpoint can see it.

    Defaults give a wide-open window centred on today — tests that need
    out-of-window behaviour pass explicit `start`/`end`.
    """
    today = date.today()
    rule = Rule(
        tenant_id=tenant.id,
        name=name,
        description=description,
        rule_type="campaign",
        transaction_type="fund",
        reward_type="points",
        reward_value=reward_value,
        campaign_start_date=start if start is not None else today - timedelta(days=1),
        campaign_end_date=end if end is not None else today + timedelta(days=30),
        status=status,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


async def _user_header(user: User) -> dict[str, str]:
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_featured_returns_active_campaign(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer sees the active featured campaign for their tenant."""
    rule = await _seed_campaign(db_session, test_tenant)

    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers=await _user_header(test_user),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["campaign"] is not None
    assert body["campaign"]["id"] == str(rule.id)
    assert body["campaign"]["name"] == "Spring Bonus"
    assert body["campaign"]["description"] == "Earn extra points on every fund"
    assert body["campaign"]["reward_type"] == "points"
    assert Decimal(body["campaign"]["reward_value"]) == Decimal("100")


@pytest.mark.asyncio
async def test_featured_returns_null_when_no_campaigns(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer with no running campaigns sees an empty card, not an error."""
    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers=await _user_header(test_user),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"campaign": None}


@pytest.mark.asyncio
async def test_featured_skips_inactive_campaigns(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer does not see a campaign that has been switched off."""
    await _seed_campaign(db_session, test_tenant, status="inactive")

    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers=await _user_header(test_user),
    )

    assert response.status_code == 200
    assert response.json()["campaign"] is None


@pytest.mark.asyncio
async def test_featured_skips_out_of_window_campaigns(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer does not see a campaign whose dates have passed.

    Defence-in-depth alongside the evaluator's same-day window check —
    keeps the mobile card from advertising a campaign the rules engine
    would refuse to fire.
    """
    today = date.today()
    await _seed_campaign(
        db_session,
        test_tenant,
        start=today - timedelta(days=30),
        end=today - timedelta(days=1),
    )

    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers=await _user_header(test_user),
    )

    assert response.status_code == 200
    assert response.json()["campaign"] is None


@pytest.mark.asyncio
async def test_featured_returns_newest_campaign_first(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a customer sees the most recently launched campaign when several run."""
    older = await _seed_campaign(db_session, test_tenant, name="Older")
    newer = await _seed_campaign(db_session, test_tenant, name="Newer")
    # Sanity check: created_at ordering matches insertion.
    assert newer.created_at >= older.created_at

    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers=await _user_header(test_user),
    )

    assert response.status_code == 200
    assert response.json()["campaign"]["id"] == str(newer.id)


@pytest.mark.asyncio
async def test_featured_isolates_across_tenants(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    other_tenant: Tenant,
) -> None:
    """Verify a customer never sees a featured campaign belonging to another tenant."""
    await _seed_campaign(db_session, other_tenant, name="Cross-tenant Bonus")

    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers=await _user_header(test_user),
    )

    assert response.status_code == 200
    assert response.json()["campaign"] is None


@pytest.mark.asyncio
async def test_featured_requires_session_token(
    async_client: AsyncClient,
) -> None:
    """Verify a signed-out visitor cannot see any featured campaign."""
    response = await async_client.get("/api/v1/catalog/featured")

    assert response.status_code == 401
    # Defensive — endpoint must never leak the empty-state body without auth.
    assert "campaign" not in response.text


@pytest.mark.asyncio
async def test_featured_rejects_unknown_session_token(
    async_client: AsyncClient,
) -> None:
    """Verify a visitor with an invalid session cannot see any featured campaign."""
    response = await async_client.get(
        "/api/v1/catalog/featured",
        headers={"Authorization": f"Bearer {uuid4().hex}"},
    )

    assert response.status_code == 401
