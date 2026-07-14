"""Tests for the `earned_points` field on POST /api/v1/payments/p2p.

Mirrors the fund pattern (`tests/payments/test_fund.py` where applicable):
the rules engine writes `reward_events` rows keyed by `triggering_event_id`
(the internal transaction id, stringified, for synchronous internal flows).
The P2P response surfaces the integer total of those rows so the mobile
success screen can render "+ X PTS earned" without a follow-up poll.

The existing P2P happy / sad path matrix lives in
`tests/payments/test_p2p_transfer.py`; this file is intentionally narrow —
two tests that exercise *only* the new `earned_points` plumbing.
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
    RewardEvent,
    Rule,
    Tenant,
    User,
    UserIdentifier,
)
from tests.conftest import create_session_token_for_user

# -----------------------------------------------------------------------------
# Helpers — mirror the test_p2p_transfer.py setup so this file stands alone.
# -----------------------------------------------------------------------------


async def _ensure_default_role(session: AsyncSession, tenant: Tenant):
    """Get or create the tenant's standard_user role with p2p permission.

    The Phase F.3 role check rejects P2P without an active "p2p" permission;
    every helper-created sender needs this role wired up.
    """
    from sqlalchemy import select

    from app.shared.models import Role, RolePermission

    result = await session.execute(
        select(Role).where(Role.tenant_id == tenant.id, Role.name == "standard_user")
    )
    role = result.scalar_one_or_none()
    if role is not None:
        return role
    role = Role(tenant_id=tenant.id, name="standard_user")
    session.add(role)
    await session.flush()
    for txn_type in ("p2p", "redemption", "fund"):
        session.add(RolePermission(role_id=role.id, transaction_type=txn_type, permitted=True))
    await session.commit()
    return role


async def _make_user_with_wallet(
    session: AsyncSession,
    tenant: Tenant,
    *,
    phone: str,
    currency: str = "ZAR",
) -> tuple[User, Account]:
    """Create a user with one verified phone identifier + a wallet + default role."""
    from app.shared.models import UserRole

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
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
    )
    session.add(wallet)
    role = await _ensure_default_role(session, tenant)
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    await session.refresh(user)
    await session.refresh(wallet)
    return user, wallet


async def _auth_header_for(user: User) -> dict[str, str]:
    """Build a Bearer header for a freshly-created user."""
    token = await create_session_token_for_user(user.id, user.tenant_id)
    return {"Authorization": f"Bearer {token}"}


async def _seed_rule(session: AsyncSession, tenant: Tenant) -> Rule:
    """Insert a minimal `first_time` rule so reward_events FK is satisfied.

    The rule itself is never evaluated in these tests — it exists only to
    satisfy the `reward_events.rule_id -> rules.id` foreign key when we
    insert a `RewardEvent` directly.
    """
    rule = Rule(
        tenant_id=tenant.id,
        name="test-earned-points-rule",
        rule_type="first_time",
        transaction_type="p2p",
        reward_type="points",
        reward_value=Decimal("100"),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2p_response_includes_earned_points_field(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """A normal P2P (no rules fired) returns `earned_points: null`.

    The mobile app reads `body["earned_points"]` to decide whether to
    show the "+ X PTS earned" toast. The field must be present on every
    response — `null` when no rules ran, an integer otherwise. This test
    asserts presence + null-when-no-rules; the next test covers the
    integer-when-rules-fired branch.
    """
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7771")
    bob, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7772")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key=f"seed-{uuid4().hex}",
    )

    alice_auth = await _auth_header_for(alice)
    response = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": uuid4().hex},
        json={
            "recipient": {
                "identifier_type": "phone",
                "identifier_value": "+27 82 555 7772",
            },
            "amount": "50",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Bob exists; the transfer landed.
    assert body["recipient_user_id"] == str(bob.id)

    # The earned_points key MUST be present (mobile relies on it). Today no
    # synchronous rules fire on P2P, so the value is null.
    assert "earned_points" in body
    assert body["earned_points"] is None


@pytest.mark.asyncio
async def test_p2p_earned_points_reflects_rule_issuance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """A `RewardEvent` keyed to the txn surfaces as `earned_points` on replay.

    Flow:
      1. Send a P2P (txn id T, response says earned_points=null).
      2. Seed a `RewardEvent` whose `triggering_event_id == str(T)`.
      3. Replay the SAME request with the same Idempotency-Key — the
         payments service short-circuits to the original txn but still
         runs `_resolve_earned_points_for_txn`, which now finds the
         seeded row and returns its value.
      4. Assert the response shows earned_points == 75.

    The replay path proves the resolver is wired into the response
    construction; a single seeded row is sufficient since the resolver
    is a SUM aggregate that already collapses to identity for one row.
    """
    alice, _ = await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 8881")
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 8882")
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=alice.id,
        amount=Decimal("500"),
        currency="ZAR",
        idempotency_key=f"seed-{uuid4().hex}",
    )
    rule = await _seed_rule(db_session, test_tenant)

    idempotency_key = uuid4().hex
    alice_auth = await _auth_header_for(alice)
    payload = {
        "recipient": {
            "identifier_type": "phone",
            "identifier_value": "+27 82 555 8882",
        },
        "amount": "120",
        "currency": "ZAR",
    }

    # Step 1 — first call. No reward_events exist yet, so earned_points is null.
    first = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": idempotency_key},
        json=payload,
    )
    assert first.status_code == 201, first.text
    txn_id = first.json()["transaction_id"]
    assert first.json()["earned_points"] is None

    # Step 2 — seed one reward_event tied to the txn id (string form, matches
    # the resolver's `RewardEvent.triggering_event_id == str(txn_id)` query).
    db_session.add(
        RewardEvent(
            user_id=alice.id,
            rule_id=rule.id,
            triggering_event_id=txn_id,
            reward_type="points",
            reward_value=Decimal("75"),
        )
    )
    await db_session.commit()

    # Step 3 — replay. Idempotency returns the original txn; the resolver
    # now finds the reward_event for it and surfaces 75.
    second = await async_client.post(
        "/api/v1/payments/p2p",
        headers={**alice_auth, "Idempotency-Key": idempotency_key},
        json=payload,
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == txn_id
    assert second.json()["earned_points"] == 75
