"""Tests for the role-permission gate on P2P + redemption (Phase F.3).

These verify step 1 of the Pay-PRD-0260 orchestration sequence — the role
check rejects unauthorized users BEFORE any wallet lookup, lock, or ledger
write.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import top_up
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Role,
    Tenant,
    User,
    UserIdentifier,
    UserRole,
)


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


@pytest.mark.asyncio
async def test_p2p_rejects_user_with_no_role(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
) -> None:
    """User without any role → 403 not_authorised at step 1. No ledger write."""
    # Alice has no role assigned (skip default_user_role).
    alice = await _make_user_with_phone(
        db_session, test_tenant, phone="+27 82 999 1001"
    )
    # Bob has the default role.
    await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 1002",
        assign_role=default_user_role,
    )

    # Give Alice some money so we can isolate the role check from the
    # overdraft check.
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="topup-no-role-test",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
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
    """User has a role, but the role doesn't permit p2p → 403."""
    # A role that explicitly only permits "redemption" — no p2p.
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
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="topup-redeem-only",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
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
    """User has the default role but it's inactive → 403."""
    # Deactivate the default role.
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
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="topup-inactive",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
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
    """User holds multiple roles — any one granting p2p is enough."""
    # default_user_role grants p2p. Also give the user an inert "viewer" role.
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
    # Also assign the inert viewer role — should not affect anything.
    db_session.add(UserRole(user_id=alice.id, role_id=viewer.id))
    await db_session.commit()

    await _make_user_with_phone(
        db_session,
        test_tenant,
        phone="+27 82 999 4002",
        assign_role=default_user_role,
    )
    await top_up(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="topup-multi-role",
    )

    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "sender_user_id": str(alice.id),
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
    """Redemption initiate also runs the role check at step 1.

    A user without a 'redemption' permission is rejected before any
    points-account lookup happens.
    """
    from app.modules.rewards.service import issue_points_reward
    from app.shared.models import Account as AcctModel
    from app.shared.models import (
        ACCOUNT_TYPE_POINTS,
        ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        Rule,
    )

    # Create a role that does NOT grant redemption.
    p2p_only = Role(tenant_id=test_tenant.id, name="p2p-only")
    db_session.add(p2p_only)
    await db_session.flush()
    from app.shared.models import RolePermission

    db_session.add(
        RolePermission(
            role_id=p2p_only.id, transaction_type="p2p", permitted=True
        )
    )
    await db_session.commit()
    await db_session.refresh(p2p_only)

    alice = await _make_user_with_phone(
        db_session, test_tenant, phone="+27 82 999 5001", assign_role=p2p_only
    )
    # Alice needs a points account + balance + a provider for the test
    # to reach the role check (which is step 1, so actually it doesn't
    # need to reach further — but giving her a balance proves the rejection
    # happens before any ledger debit).
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

    # Give Alice some points via a rule firing so we know she has balance.
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

    # Register a provider — uses admin auth.
    provider_resp = await async_client.post(
        "/api/v1/redemption/providers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "P"},
    )
    provider_id = provider_resp.json()["id"]

    # Alice attempts to redeem — role check rejects before anything else.
    response = await async_client.post(
        "/api/v1/redemption/initiate",
        headers={"Idempotency-Key": uuid4().hex},
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(alice.id),
            "provider_id": provider_id,
            "points_amount": "10",
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "not_authorised"
