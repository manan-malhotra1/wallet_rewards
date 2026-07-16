"""Tests for the step-up PIN enforcement on POST /api/v1/payments/p2p."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_pin
from app.modules.payments.service import fund
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Role,
    RolePermission,
    StepUpPolicy,
    Tenant,
    User,
    UserIdentifier,
    UserRole,
)
from tests.conftest import create_session_token_for_user


async def _make_tenant_user_with_pin(
    session: AsyncSession,
    tenant: Tenant,
    *,
    phone: str,
    pin: str = "1234",
) -> tuple[User, Account]:
    """Build a user + ZAR wallet + standard_user role + a known PIN.

    Returns (user, wallet). The PIN is bcrypt-hashed on the user row so
    the step-up verification path exercises the real `hashing.verify_pin`.
    """
    # Ensure a standard_user role exists with p2p permission.
    from sqlalchemy import select

    role = (
        await session.execute(
            select(Role).where(Role.tenant_id == tenant.id, Role.name == "standard_user")
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(tenant_id=tenant.id, name="standard_user")
        session.add(role)
        await session.flush()
        for txn_type in ("p2p", "redemption", "fund"):
            session.add(RolePermission(role_id=role.id, transaction_type=txn_type))
        await session.commit()

    user = User(tenant_id=tenant.id, pin_hash=hash_pin(pin))
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=phone,
            verified=True,
        )
    )
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    await session.refresh(user)
    return user, wallet


@pytest_asyncio.fixture(autouse=True)
async def _seed_p2p_config(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Autouse: seed a zero-fee p2p pricing + limit config for every test here.

    Invariant #12 makes the pricing+limit gate unconditional, so a p2p can only
    reach the step-up logic these tests exercise once both configs exist. Zero
    fee keeps the step-up amounts unaffected. No test in this file is a
    missing-config negative test, so seeding unconditionally is safe.
    """
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config

    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        ),
    )
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )


async def _seed_p2p_policy(session: AsyncSession, tenant: Tenant, threshold: str = "200") -> None:
    """Insert a step-up policy: P2P over `threshold` ZAR requires PIN."""
    session.add(
        StepUpPolicy(
            tenant_id=tenant.id,
            transaction_type="p2p",
            currency="ZAR",
            threshold_amount=Decimal(threshold),
        )
    )
    await session.commit()


async def _auth_header(user: User) -> dict[str, str]:
    """Build a session-token Bearer header for the user."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


def _idem() -> dict[str, str]:
    """Fresh Idempotency-Key header per call."""
    return {"Idempotency-Key": uuid4().hex}


@pytest.mark.asyncio
async def test_p2p_below_threshold_no_pin_needed(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Threshold R 200; sending R 100 should succeed without a PIN."""
    alice, _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 1111")
    bob, _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 2222")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-bel-1",
    )
    await _seed_p2p_policy(db_session, test_tenant, threshold="200")

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _auth_header(alice)), **_idem()},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 555 2222",
            },
            "amount": "100",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["recipient_user_id"] == str(bob.id)


@pytest.mark.asyncio
async def test_p2p_above_threshold_without_pin_returns_step_up_required(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """R 500 over a R 200 threshold without a PIN → 401 step_up_required."""
    alice, _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 3333")
    _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 4444")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-step-1",
    )
    await _seed_p2p_policy(db_session, test_tenant, threshold="200")

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _auth_header(alice)), **_idem()},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 555 4444",
            },
            "amount": "500",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 401, response.text
    assert response.json()["error_code"] == "step_up_required"


@pytest.mark.asyncio
async def test_p2p_above_threshold_with_wrong_pin_returns_invalid_step_up_pin(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Wrong PIN with a step-up-required amount → 401 invalid_step_up_pin."""
    alice, _ = await _make_tenant_user_with_pin(
        db_session, test_tenant, phone="+27 82 555 5555", pin="1234"
    )
    _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 6666")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-step-2",
    )
    await _seed_p2p_policy(db_session, test_tenant, threshold="200")

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _auth_header(alice)), **_idem()},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 555 6666",
            },
            "amount": "500",
            "currency": "ZAR",
            "pin": "9999",
        },
    )
    assert response.status_code == 401, response.text
    assert response.json()["error_code"] == "invalid_step_up_pin"


@pytest.mark.asyncio
async def test_p2p_above_threshold_with_correct_pin_succeeds(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Correct PIN with a step-up-required amount → 201 + ledger writes."""
    alice, _ = await _make_tenant_user_with_pin(
        db_session, test_tenant, phone="+27 82 555 7777", pin="1234"
    )
    bob, _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 8888")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("1000"),
        currency="ZAR",
        idempotency_key="seed-step-3",
    )
    await _seed_p2p_policy(db_session, test_tenant, threshold="200")

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _auth_header(alice)), **_idem()},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 555 8888",
            },
            "amount": "500",
            "currency": "ZAR",
            "pin": "1234",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["recipient_user_id"] == str(bob.id)
    assert body["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_p2p_no_policy_means_no_step_up(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """With no policy row, even a huge amount goes through without a PIN."""
    alice, _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 9999")
    _ = await _make_tenant_user_with_pin(db_session, test_tenant, phone="+27 82 555 0000")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("10000"),
        currency="ZAR",
        idempotency_key="seed-step-4",
    )
    # NO step-up policy seeded.

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _auth_header(alice)), **_idem()},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 555 0000",
            },
            "amount": "9000",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
