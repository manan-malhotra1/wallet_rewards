"""Tests for POST /api/v1/redemption/initiate.

Covers the overdraft-prevention scenarios from Phase D threat model §5.
"""
from __future__ import annotations

import asyncio
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


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


@pytest.fixture
def idempotency_header() -> dict[str, str]:
    """Fresh Idempotency-Key per request."""
    return {"Idempotency-Key": uuid4().hex}


async def _register_provider(
    async_client: AsyncClient, tenant: Tenant, *, name: str = "Test Provider"
) -> str:
    """Register a provider via the API and return its id."""
    resp = await async_client.post(
        "/api/v1/redemption/providers",
        json={"tenant_id": str(tenant.id), "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _credit_user_points(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    amount: Decimal,
    *,
    seed_key: str = "seed-pts",
) -> None:
    """Give the user some points by routing an ad-hoc reward through issue_points_reward."""
    rule = Rule(
        tenant_id=tenant.id,
        name=f"seed-rule-{seed_key}",
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
        triggering_event_id=seed_key,
        reward_value=amount,
    )


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,  # noqa: ARG001 — required for issuance
    idempotency_header: dict[str, str],
) -> None:
    """Alice 150 pts → redeem 100 → PENDING redemption, available drops to 50."""
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("150"), seed_key="happy"
    )
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "provider_id": provider_id,
            "points_amount": "100",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    assert Decimal(body["points_amount"]) == Decimal("100")

    # The pending DEBIT counts as reserved — available drops by 100.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("150")
    assert reserved == Decimal("100")
    assert balance - reserved == Decimal("50")


@pytest.mark.asyncio
async def test_initiate_rejects_insufficient_points(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,  # noqa: ARG001
    idempotency_header: dict[str, str],
) -> None:
    """Redeeming more than available → 409 insufficient_funds, no ledger write."""
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("50"), seed_key="insuf"
    )
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "provider_id": provider_id,
            "points_amount": "200",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "insufficient_funds"

    # Balance untouched, no reserved.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("50")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_initiate_rejects_unknown_provider(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
    idempotency_header: dict[str, str],
) -> None:
    """Unknown provider_id → 404."""
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("100"), seed_key="up"
    )
    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "provider_id": str(uuid4()),
            "points_amount": "10",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "provider_not_found"


@pytest.mark.asyncio
async def test_initiate_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Same Idempotency-Key returns same redemption_id — no double-debit."""
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("100"), seed_key="idem"
    )
    provider_id = await _register_provider(async_client, test_tenant)
    key = uuid4().hex
    payload = {
        "tenant_id": str(test_tenant.id),
        "user_id": str(test_user.id),
        "provider_id": provider_id,
        "points_amount": "30",
    }

    first = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    second = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={"Idempotency-Key": key},
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    # Only ONE reserved 30 — not 60.
    _, reserved = await derive_balance(db_session, user_points.id)
    assert reserved == Decimal("30")


@pytest.mark.asyncio
async def test_initiate_concurrent_double_spend_blocked(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,  # noqa: ARG001
) -> None:
    """Two simultaneous full-balance redemptions: only ONE succeeds.

    The SELECT FOR UPDATE on user.points_account serialises them.
    """
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("100"), seed_key="race"
    )
    provider_id = await _register_provider(async_client, test_tenant)

    def request(key: str):
        return asyncio.create_task(
            async_client.post(
                "/api/v1/redemption/initiate",
                headers={"Idempotency-Key": key},
                json={
                    "tenant_id": str(test_tenant.id),
                    "user_id": str(test_user.id),
                    "provider_id": provider_id,
                    "points_amount": "100",
                },
            )
        )

    res_a, res_b = await asyncio.gather(
        request(uuid4().hex), request(uuid4().hex)
    )
    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one 201 + one 409, got {statuses}"


@pytest.mark.asyncio
async def test_initiate_cross_tenant_provider_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,  # noqa: ARG001
    system_points_account: Account,  # noqa: ARG001
    idempotency_header: dict[str, str],
) -> None:
    """Provider exists in other_tenant; request in test_tenant → 404 (no leak)."""
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("100"), seed_key="xt"
    )
    other_provider_id = await _register_provider(
        async_client, other_tenant, name="Other Provider"
    )

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers=idempotency_header,
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "provider_id": other_provider_id,
            "points_amount": "10",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "provider_not_found"
