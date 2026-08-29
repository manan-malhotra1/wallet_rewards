"""Customer rewards summary and redemption history.

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
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    PointsConversionRate,
    Rule,
    StepUpPolicy,
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
    """Verify a customer who has earned no points sees a blank summary."""
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
    """Verify a customer's summary shows the total points they have earned."""
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
    """Verify a customer's summary shows the total points they have redeemed.

    Mixes auth contexts: admin for provider + confirm, user for initiate +
    catalog read.
    """
    await _seed_reward(db_session, test_tenant, test_user, Decimal("200"), key="r1")

    await seed_redemption_service_config(db_session, test_tenant)
    # Step-up is fail-closed (no policy → PIN for any amount); test_user has no
    # PIN. This test covers redeemed-balance accounting, not step-up, so seed a
    # redemption policy above the 80-point redeem to wave it through.
    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="redemption",
            currency="PTS",
            threshold_amount=Decimal("1000"),
        )
    )
    await db_session.commit()
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
    """Verify a customer's redemption history lists their most recent redeems first.

    Backed by internal (points to wallet) redemptions — the provider path is gone.
    """
    await _seed_reward(db_session, test_tenant, test_user, Decimal("100"), key="h")
    await seed_redemption_service_config(db_session, test_tenant)
    # Step-up is fail-closed (no policy → PIN for any amount); test_user has no
    # PIN. This test covers redemption history, not step-up, so seed a
    # redemption policy above the redeem amounts to wave them through.
    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="redemption",
            currency="PTS",
            threshold_amount=Decimal("1000"),
        )
    )
    await db_session.commit()
    # Internal redemption needs a conversion rate for the payout currency, a ZAR
    # wallet to pay into, and a funded cashback wallet to pay from.
    db_session.add(
        PointsConversionRate(
            tenant_id=test_tenant.id,
            currency="ZAR",
            points_per_unit=Decimal("100"),
            value_per_unit=Decimal("10"),
            status="active",
        )
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()
    # The tenant fixture already prefunds the cashback wallet (conftest), and
    # the helper is not idempotent, so calling it again here would 409.

    user_header = await _user_header(test_user)
    # Two redemptions, smallest first, so the newest-first assertion below is
    # about ordering rather than about which amount happens to be larger.
    for amount in ("10", "20"):
        response = await async_client.post(
            "/api/v1/redemption/internal",
            headers={**user_header, "Idempotency-Key": uuid4().hex},
            json={"points_amount": amount, "currency": "ZAR"},
        )
        assert response.status_code == 201, response.text

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
    # The history now reports what actually landed in the wallet: at
    # 100 PTS = 10 ZAR, 20 points is R2.00.
    assert items[0]["currency"] == "ZAR"
    assert Decimal(items[0]["fiat_amount"]) == Decimal("2.00")
