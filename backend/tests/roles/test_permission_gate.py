"""Role-permission gate on transfers and redemptions.

These verify step 1 of the Pay-PRD-0260 orchestration sequence — the role
check rejects unauthorized users BEFORE any wallet lookup, lock, or ledger
write.

Phase F.4 layered session-token auth on top. These tests mint a session for
the test user (Alice) and assert the role-gate still fires correctly.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import fund
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Role,
    StepUpPolicy,
    Tenant,
    User,
    UserIdentifier,
    UserRole,
)
from tests.conftest import create_session_token_for_user


async def _make_user_with_phone(
    session: AsyncSession,
    tenant: Tenant,
    *,
    phone: str,
    assign_role: Role | None = None,
) -> User:
    """Create a user + phone identifier; optionally assign a role."""
    user = User(tenant_id=tenant.id)
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
    session.add(
        Account(
            tenant_id=tenant.id,
            user_id=user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    if assign_role is not None:
        session.add(UserRole(user_id=user.id, role_id=assign_role.id))
    await session.commit()
    await session.refresh(user)
    return user


async def _user_header(user: User) -> dict[str, str]:
    """Mint a Bearer session header for a user."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_p2p_rejects_user_with_no_role(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
) -> None:
    """Verify a customer with no role assigned cannot send money."""
    alice = await _make_user_with_phone(db_session, test_tenant, phone="+27 82 999 1001")
    await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 1002",
        assign_role=default_user_role,
    )

    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="fund-no-role-test",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _user_header(alice)), "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 999 1002",
            },
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "not_authorised"


@pytest.mark.asyncio
async def test_p2p_rejects_user_whose_role_lacks_p2p_permission(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a customer whose role does not allow transfers is blocked."""
    from app.shared.models import RolePermission

    redemption_only = Role(
        tenant_id=test_tenant.id,
        name="redeem-only",
    )
    db_session.add(redemption_only)
    await db_session.flush()
    db_session.add(
        RolePermission(
            role_id=redemption_only.id,
            transaction_type="redemption",
            permitted=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(redemption_only)

    alice = await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 2001",
        assign_role=redemption_only,
    )
    await _make_user_with_phone(
        db_session, test_tenant, phone="+27 82 999 2002", assign_role=redemption_only
    )
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="fund-redeem-only",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _user_header(alice)), "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 999 2002",
            },
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "not_authorised"


@pytest.mark.asyncio
async def test_p2p_rejects_when_role_is_inactive(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
) -> None:
    """Verify a customer whose role has been deactivated cannot transfer."""
    default_user_role.status = "inactive"
    await db_session.commit()

    alice = await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 3001",
        assign_role=default_user_role,
    )
    await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 3002",
        assign_role=default_user_role,
    )
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="fund-inactive",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _user_header(alice)), "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 999 3002",
            },
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_p2p_allowed_when_any_role_grants_permission(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
) -> None:
    """Verify a customer can transfer when any one of their roles allows it."""
    # Invariant #12: the pricing+limit gate is unconditional, so this success
    # path needs both configs seeded (the 403 tests fail earlier, at the role
    # check, so they need no config). Zero fee — this test asserts only status.
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
    # Step-up is fail-closed: with no policy any amount demands a PIN. This test
    # exercises the role gate, not step-up, and its users carry no PIN — so seed
    # a p2p policy whose threshold sits above the ZAR 10 transfer to wave it
    # through (matches tests/step_up/_seed_p2p_policy).
    db_session.add(
        StepUpPolicy(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            currency="ZAR",
            threshold_amount=Decimal("1000"),
        )
    )
    await db_session.commit()
    viewer = Role(tenant_id=test_tenant.id, name="viewer")
    db_session.add(viewer)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(viewer)

    alice = await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 4001",
        assign_role=default_user_role,
    )
    db_session.add(UserRole(user_id=alice.id, role_id=viewer.id))
    await db_session.commit()

    await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 4002",
        assign_role=default_user_role,
    )
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="fund-multi-role",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**(await _user_header(alice)), "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 999 4002",
            },
            "amount": "10",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_redemption_initiate_also_gated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer without redemption permission cannot redeem points.

    A user without a 'redemption' permission is rejected before any
    points-account lookup happens.
    """
    from app.modules.rewards.service import issue_points_reward
    from app.shared.models import (
        ACCOUNT_TYPE_POINTS,
        ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        RolePermission,
        Rule,
    )
    from app.shared.models import Account as AcctModel

    p2p_only = Role(tenant_id=test_tenant.id, name="p2p-only")
    db_session.add(p2p_only)
    await db_session.flush()
    db_session.add(RolePermission(role_id=p2p_only.id, transaction_type="p2p", permitted=True))
    await db_session.commit()
    await db_session.refresh(p2p_only)

    alice = await _make_user_with_phone(
        db_session, test_tenant, phone="+27 82 999 5001", assign_role=p2p_only
    )
    db_session.add(
        AcctModel(
            tenant_id=test_tenant.id,
            user_id=alice.id,
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
        )
    )
    db_session.add(
        AcctModel(
            tenant_id=test_tenant.id,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
        )
    )
    await db_session.commit()

    rule = Rule(
        tenant_id=test_tenant.id,
        name="grant-pts",
        rule_type="first_time",
        transaction_type="seed",
        reward_type="points",
        reward_value=Decimal("100"),
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    await issue_points_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        rule=rule,
        triggering_event_id="grant-pts-seed",
        reward_value=Decimal("100"),
    )

    # Provider register requires admin (Phase F.4).
    provider_resp = await async_client.post(
        "/api/v1/redemption/providers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "P"},
    )
    provider_id = provider_resp.json()["id"]

    # Alice attempts to redeem with her own session — role check rejects.
    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={**(await _user_header(alice)), "Idempotency-Key": uuid4().hex},
        json={
            "provider_id": provider_id,
            "points_amount": "10",
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "not_authorised"
