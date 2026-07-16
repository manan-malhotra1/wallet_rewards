"""Tests for confirm + fail lifecycle of a redemption.

Phase F.4: confirm + fail are admin-only. Initiate (used in setup) is
user-only — the helper mints a session token for the test user.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    Account,
    Rule,
    Tenant,
    User,
)
from tests.conftest import create_session_token_for_user, seed_redemption_service_config


async def _credit_and_initiate(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    credit_amount: Decimal,
    redeem_amount: Decimal,
    seed_key: str,
) -> str:
    """Seed points + register provider + initiate redemption.

    Returns the redemption_id. Uses the admin-authed async_client for the
    provider register call, and a user session token for the initiate call.
    """
    rule = Rule(
        tenant_id=tenant.id,
        name=f"seed-rule-{seed_key}",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=credit_amount,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        rule=rule,
        triggering_event_id=seed_key,
        reward_value=credit_amount,
    )

    # Redemption is fail-closed gated (invariant #12): seed its pricing + limit
    # config so this setup `/initiate` succeeds (the gate is exercised directly
    # in test_initiate_redemption.py, not here).
    await seed_redemption_service_config(db_session, tenant)

    pr = await async_client.post(
        "/api/v1/redemption/providers",
        json={"tenant_id": str(tenant.id), "name": "Provider"},
    )
    provider_id = pr.json()["id"]

    # Initiate requires a user session — admin auth would 401.
    user_token = await create_session_token_for_user(user.id, user.tenant_id)
    rs = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={
            "Idempotency-Key": uuid4().hex,
            "Authorization": f"Bearer {user_token}",
        },
        json={
            "provider_id": provider_id,
            "points_amount": str(redeem_amount),
        },
    )
    assert rs.status_code == 201, rs.text
    return rs.json()["id"]


@pytest.mark.asyncio
async def test_confirm_marks_completed_and_drops_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Confirm: PENDING entries flip to COMPLETED, balance permanently drops."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("200"),
        redeem_amount=Decimal("80"),
        seed_key="confirm",
    )

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/confirm",
        json={
            "tenant_id": str(test_tenant.id),
            "external_reference": "MUKURU-XYZ",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["external_reference"] == "MUKURU-XYZ"
    assert body["completed_at"] is not None

    # Balance permanently drops to 120; reserved = 0.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("120")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_fail_restores_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Fail: PENDING entries flip to REVERSED, balance restored."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("75"),
        seed_key="fail",
    )

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/fail",
        json={
            "tenant_id": str(test_tenant.id),
            "reason": "provider rejected",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["failure_reason"] == "provider rejected"

    # Balance restored — REVERSED entries don't count.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("100")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_confirm_response_carries_user_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """The admin confirm override resolves user_name (phone fallback here).

    `test_user` has a phone identifier but no profile, so the resolved name is
    the normalised phone value rather than a bare id.
    """
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("30"),
        seed_key="uname-confirm",
    )
    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/confirm",
        json={"tenant_id": str(test_tenant.id)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user_name"] == test_user.identifiers[0].identifier_value


@pytest.mark.asyncio
async def test_fail_response_carries_user_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """The admin fail override also resolves and returns user_name."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("30"),
        seed_key="uname-fail",
    )
    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/fail",
        json={"tenant_id": str(test_tenant.id), "reason": "provider rejected"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user_name"] == test_user.identifiers[0].identifier_value


@pytest.mark.asyncio
async def test_confirm_then_confirm_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Cannot confirm a redemption that's already terminal."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("50"),
        seed_key="dconf",
    )
    body = {"tenant_id": str(test_tenant.id)}
    first = await async_client.post(f"/api/v1/redemption/{redemption_id}/confirm", json=body)
    assert first.status_code == 200
    second = await async_client.post(f"/api/v1/redemption/{redemption_id}/confirm", json=body)
    assert second.status_code == 409
    assert second.json()["error_code"] == "redemption_not_pending"


@pytest.mark.asyncio
async def test_confirm_cross_tenant_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Cross-tenant confirm → 404 (no existence leak)."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("20"),
        seed_key="xtc",
    )

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/confirm",
        json={"tenant_id": str(other_tenant.id)},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "redemption_not_found"


@pytest.mark.asyncio
async def test_fail_cross_tenant_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Cross-tenant fail → 404 (mirror of cross-tenant confirm)."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("20"),
        seed_key="xtf",
    )

    response = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/fail",
        json={
            "tenant_id": str(other_tenant.id),
            "reason": "attempted from wrong tenant",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "redemption_not_found"


@pytest.mark.asyncio
async def test_confirm_then_fail_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Once COMPLETED a redemption is terminal — cannot transition to FAILED."""
    redemption_id = await _credit_and_initiate(
        async_client,
        db_session,
        test_tenant,
        test_user,
        credit_amount=Decimal("100"),
        redeem_amount=Decimal("40"),
        seed_key="cthen-f",
    )

    confirm = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/confirm",
        json={"tenant_id": str(test_tenant.id)},
    )
    assert confirm.status_code == 200

    fail = await async_client.post(
        f"/api/v1/redemption/{redemption_id}/fail",
        json={
            "tenant_id": str(test_tenant.id),
            "reason": "too late",
        },
    )
    assert fail.status_code == 409
    assert fail.json()["error_code"] == "redemption_not_pending"
