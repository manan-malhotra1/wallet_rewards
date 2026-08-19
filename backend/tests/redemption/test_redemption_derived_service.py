"""Redemption wired to `resolve_service_code` (Task 6, mechanical replication
of the P2P reference wiring in `tests/payments/test_p2p_derived_service.py`).

An optional `service_code` on the initiate-redemption request is resolved
ONCE before the permission check, and the resolved code drives everything
downstream while `base_transaction_type` always records the endpoint's own
base ('redemption'). These tests prove: the omitted-`service_code` path is
unchanged, and a derived service records its own code + the base, charging
its own (different) fee.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rewards.service import issue_points_reward
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    Account,
    LimitConfig,
    PricingConfig,
    Role,
    RolePermission,
    Rule,
    Service,
    Tenant,
    Transaction,
    User,
    UserRole,
)
from tests.conftest import create_session_token_for_user

_REDEMPTION_CURRENCY = "PTS"


@pytest.fixture
def idempotency_header() -> dict[str, str]:
    """Fresh Idempotency-Key per request (mirrors test_initiate_redemption.py —
    a file-local fixture, no shared conftest defines it for this module)."""
    return {"Idempotency-Key": uuid4().hex}


@pytest_asyncio.fixture
async def redemption_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed a zero-fee pricing + wide limit config for 'redemption' so the
    fail-closed gate passes (mirrors test_initiate_redemption.py's fixture)."""
    db_session.add(
        PricingConfig(
            tenant_id=test_tenant.id,
            transaction_type="redemption",
            account_type=ACCOUNT_TYPE_POINTS,
            currency=_REDEMPTION_CURRENCY,
            fixed_fee=Decimal("0"),
        )
    )
    db_session.add(
        LimitConfig(
            tenant_id=test_tenant.id,
            transaction_type="redemption",
            account_type=ACCOUNT_TYPE_POINTS,
            currency=_REDEMPTION_CURRENCY,
            min_amount=Decimal("1"),
            max_amount=Decimal("1000000"),
        )
    )
    await db_session.commit()


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
    session: AsyncSession, tenant: Tenant, user: User, amount: Decimal, *, seed_key: str
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
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    await issue_points_reward(
        session,
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


async def _seed_derived_redemption_service(
    session: AsyncSession, tenant: Tenant, code: str = "redemption_express"
) -> Service:
    """Persist a live derived service based on 'redemption' (Task 4 fixture shape)."""
    base = Service(tenant_id=tenant.id, code="redemption", display_name="Redemption", kind="base")
    session.add(base)
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name="Express Redemption",
        kind="derived",
        base_service_code="redemption",
    )
    session.add(row)
    await session.commit()
    return row


async def _grant_permission(session: AsyncSession, user: User, transaction_type: str) -> None:
    """Grant `user` a role permitting `transaction_type`."""
    role = Role(tenant_id=user.tenant_id, name=f"grant-{transaction_type}-{uuid4().hex[:8]}")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, transaction_type=transaction_type, permitted=True))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_redemption_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    redemption_configs: None,
    idempotency_header: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'redemption' byte for byte"""
    await _credit_user_points(db_session, test_tenant, test_user, Decimal("150"), seed_key="omit")
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={"provider_id": provider_id, "points_amount": "100"},
    )
    assert response.status_code == 201, response.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == response.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "redemption"
    assert txn.base_transaction_type == "redemption"


@pytest.mark.asyncio
async def test_derived_redemption_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
    redemption_configs: None,
    idempotency_header: dict[str, str],
) -> None:
    """Verify a derived redemption service resolves, records the derived code +
    base 'redemption', and charges a fee that DIFFERS from the base's zero fee
    (pricing / limits are never inherited — spec §6.2)."""
    await _seed_derived_redemption_service(db_session, test_tenant)
    db_session.add(
        PricingConfig(
            tenant_id=test_tenant.id,
            transaction_type="redemption_express",
            account_type=ACCOUNT_TYPE_POINTS,
            currency=_REDEMPTION_CURRENCY,
            fixed_fee=Decimal("10"),
        )
    )
    db_session.add(
        LimitConfig(
            tenant_id=test_tenant.id,
            transaction_type="redemption_express",
            account_type=ACCOUNT_TYPE_POINTS,
            currency=_REDEMPTION_CURRENCY,
            min_amount=Decimal("1"),
            max_amount=Decimal("1000000"),
        )
    )
    await db_session.commit()
    await _grant_permission(db_session, test_user, "redemption_express")
    await _credit_user_points(
        db_session, test_tenant, test_user, Decimal("150"), seed_key="derived"
    )
    provider_id = await _register_provider(async_client, test_tenant)

    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_auth_header(test_user)), **idempotency_header},
        json={
            "provider_id": provider_id,
            "points_amount": "100",
            "service_code": "redemption_express",
        },
    )
    assert response.status_code == 201, response.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == response.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "redemption_express"
    assert txn.base_transaction_type == "redemption"
