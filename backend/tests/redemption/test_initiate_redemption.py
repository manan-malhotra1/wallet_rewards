"""Tests for POST /api/v1/redemption/initiate.

Covers the overdraft-prevention scenarios from Phase D threat model §5.
Phase F.4 removed `tenant_id` + `user_id` from the body — both come from
the user's session token. Provider registration remains admin-only.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    Account,
    LimitConfig,
    PricingConfig,
    Rule,
    Tenant,
    User,
)
from tests.conftest import create_session_token_for_user

# Redemption is points-scoped: its pricing + limit configs live on the
# points_account in PTS (invariant #12 fail-closed gate, Epic 23).
_REDEMPTION_CURRENCY = "PTS"


async def _seed_redemption_configs(
    session: AsyncSession,
    tenant: Tenant,
    *,
    with_pricing: bool = True,
    with_limit: bool = True,
) -> None:
    """Seed a zero-fee pricing config and/or a wide limit config for redemption.

    The fail-closed gate (invariant #12) requires BOTH a pricing and a limit
    config to resolve for the redeeming user's type before points are reserved.
    Scoped to the points_account / PTS with `user_type=NULL` so the default
    covers every user type. `with_pricing` / `with_limit` let a test seed only
    one side to prove the gate fails closed when the OTHER is missing.
    """
    if with_pricing:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type="redemption",
                account_type=ACCOUNT_TYPE_POINTS,
                currency=_REDEMPTION_CURRENCY,
                fixed_fee=Decimal("0"),
            )
        )
    if with_limit:
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type="redemption",
                account_type=ACCOUNT_TYPE_POINTS,
                currency=_REDEMPTION_CURRENCY,
                min_amount=Decimal("1"),
                max_amount=Decimal("1000000"),
            )
        )
    await session.commit()


@pytest_asyncio.fixture
async def redemption_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed redemption pricing + limit configs so the fail-closed gate passes."""
    await _seed_redemption_configs(db_session, test_tenant)


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
    """Register a provider via the admin-authed API; return its id."""
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
    """Give the user points via a synthetic first_time rule reward."""
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


async def _user_auth_header(user: User) -> dict[str, str]:
    """Mint a session token for `user` and wrap in a Bearer header."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


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
    system_points_account: Account,
    redemption_configs: None,
    idempotency_header: dict[str, str],
) -> None:
    """Alice 150 pts → redeem 100 → PENDING redemption, available drops to 50."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("150"), seed_key="happy")
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={
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
    system_points_account: Account,
    redemption_configs: None,
    idempotency_header: dict[str, str],
) -> None:
    """Redeeming more than available → 409 insufficient_funds, no ledger write."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("50"), seed_key="insuf")
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={
            "provider_id": provider_id,
            "points_amount": "200",
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "insufficient_funds"

    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("50")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_initiate_rejects_unknown_provider(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    idempotency_header: dict[str, str],
) -> None:
    """Unknown provider_id → 404."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("100"), seed_key="up")
    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={
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
    system_points_account: Account,
    redemption_configs: None,
) -> None:
    """Same Idempotency-Key returns same redemption_id — no double-debit."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("100"), seed_key="idem")
    provider_id = await _register_provider(async_client, test_tenant)
    user_header = await _user_auth_header(test_user)
    key = uuid4().hex
    payload = {
        "provider_id": provider_id,
        "points_amount": "30",
    }

    first = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**user_header, "Idempotency-Key": key},
        json=payload,
    )
    second = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**user_header, "Idempotency-Key": key},
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    _, reserved = await derive_balance(db_session, user_points.id)
    assert reserved == Decimal("30")


@pytest.mark.asyncio
async def test_initiate_concurrent_double_spend_blocked(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    redemption_configs: None,
) -> None:
    """Two simultaneous full-balance redemptions: only ONE succeeds."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("100"), seed_key="race")
    provider_id = await _register_provider(async_client, test_tenant)
    user_header = await _user_auth_header(test_user)

    def request(key: str):
        return asyncio.create_task(
            async_client.post(
                "/api/v1/redemption/initiate",
                headers={**user_header, "Idempotency-Key": key},
                json={
                    "provider_id": provider_id,
                    "points_amount": "100",
                },
            )
        )

    res_a, res_b = await asyncio.gather(request(uuid4().hex), request(uuid4().hex))
    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one 201 + one 409, got {statuses}"


@pytest.mark.asyncio
async def test_initiate_cross_tenant_provider_rejects(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    idempotency_header: dict[str, str],
) -> None:
    """Provider exists in other_tenant; test_tenant user → 404 (no leak).

    Tenant comes from Alice's session (test_tenant). She references a
    provider_id that belongs to other_tenant — the tenant-scoped lookup
    returns 404, no existence leak across tenants.
    """
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("100"), seed_key="xt")
    other_provider_id = await _register_provider(async_client, other_tenant, name="Other Provider")

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={
            "provider_id": other_provider_id,
            "points_amount": "10",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "provider_not_found"


# -----------------------------------------------------------------------------
# Fail-closed service gate (invariant #12, Epic 23)
#
# Redemption must reject 422 `service_not_configured` when EITHER a pricing OR
# a limit config is missing for the redeeming user's points scope — before any
# points are reserved.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_fails_closed_when_no_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    idempotency_header: dict[str, str],
) -> None:
    """No redemption pricing/limit config → 422, no points reserved."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("150"), seed_key="fc")
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={"provider_id": provider_id, "points_amount": "100"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"

    # No points reserved — the gate fired before the two-legged PENDING write.
    balance, reserved = await derive_balance(db_session, user_points.id)
    assert balance == Decimal("150")
    assert reserved == Decimal("0")


@pytest.mark.asyncio
async def test_initiate_fails_closed_when_only_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    idempotency_header: dict[str, str],
) -> None:
    """Limit present but pricing missing → still 422 (BOTH required)."""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("150"), seed_key="fcl")
    await _seed_redemption_configs(db_session, test_tenant, with_pricing=False)
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={"provider_id": provider_id, "points_amount": "100"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "service_not_configured"

    _, reserved = await derive_balance(db_session, user_points.id)
    assert reserved == Decimal("0")
