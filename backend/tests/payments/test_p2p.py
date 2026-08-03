"""P2P triggers rewards and returns the points earned inline (both mode).

End-to-end coverage of the P2P reward plumbing (Epic 10 pipeline wiring):

  - In a `both`-mode tenant, completing a P2P transfer enqueues a reward for
    the SENDER (via the reward_outbox row post_transaction writes atomically),
    the immediate drain fires the matching rule, and the P2P API response
    surfaces the points inline as `earned_points` for the mobile celebration.
  - In a `wallet`-mode tenant, the mode gate holds end-to-end: no outbox row,
    no reward issued, and `earned_points` is 0.

The narrower placeholder tests that previously lived here asserted a lookup by
transaction id that no longer exists — the response's `earned_points` now comes
from the live outbox drain (`attempt_immediate`), not a post-hoc reward_events
query.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import fund
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    RewardEvent,
    Rule,
    Tenant,
    User,
    UserIdentifier,
)
from tests.conftest import create_session_token_for_user, prefund_float

# -----------------------------------------------------------------------------
# Helpers — mirror the test_p2p_transfer.py setup so this file stands alone.
# -----------------------------------------------------------------------------


async def _ensure_default_role(session: AsyncSession, tenant: Tenant):
    """Get or create the tenant's standard_user role with p2p permission.

    The Phase F.3 role check rejects P2P without an active "p2p" permission;
    every helper-created sender needs this role wired up.
    """
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
    with_points: bool = False,
) -> tuple[User, Account]:
    """Create a user with a verified phone, a wallet, the default role, and
    optionally a points account.

    `with_points=True` is required for the SENDER in a rewardable flow: reward
    issuance CREDITs the user's points_account, and `issue_points_reward` raises
    (fail-open, so the reward is simply skipped) when it is missing.
    """
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
    if with_points:
        session.add(
            Account(
                tenant_id=tenant.id,
                user_id=user.id,
                account_type=ACCOUNT_TYPE_POINTS,
                currency="PTS",
            )
        )
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


async def _seed_p2p_config(session: AsyncSession, tenant_id) -> None:
    """Seed a zero-fee p2p pricing + limit config (+ high step-up threshold) for ZAR.

    Invariant #12 makes the pricing+limit gate unconditional, so any test that
    actually transacts a p2p must seed both configs first. Zero fee keeps
    balance-sensitive assertions unaffected. The step-up policy threshold is set
    far above these amounts so the below-threshold path skips the PIN and the
    reward plumbing runs.
    """
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config
    from app.shared.models import StepUpPolicy

    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        ),
    )
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    session.add(
        StepUpPolicy(
            tenant_id=tenant_id,
            transaction_type="p2p",
            currency="ZAR",
            threshold_amount=Decimal("100000000"),
        )
    )
    await session.commit()


async def _seed_first_time_p2p_points_rule(
    session: AsyncSession, tenant: Tenant, *, reward_value: Decimal
) -> Rule:
    """Seed an ACTIVE first_time p2p rule that awards `reward_value` points.

    A first_time rule fires exactly once for a user's first matching p2p, which
    is all these single-transfer tests need. `status` defaults to 'active'.
    """
    rule = Rule(
        tenant_id=tenant.id,
        name="first-p2p-points",
        rule_type="first_time",
        transaction_type="p2p",
        reward_type="points",
        reward_value=reward_value,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def _reward_event_count(session: AsyncSession, user_id) -> int:
    """Count reward_events rows for a user (across all rules)."""
    return (
        await session.execute(
            select(func.count()).select_from(RewardEvent).where(RewardEvent.user_id == user_id)
        )
    ).scalar_one()


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p2p_in_both_mode_earns_points_and_returns_them_inline(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a transfer earns points and the sender sees them on the success screen.

    In a full wallet+rewards ('both') tenant with an active first-transfer rule,
    sending money issues the sender the configured points AND the P2P response
    carries `earned_points` inline so the mobile app can celebrate without a
    follow-up request.
    """
    # test_tenant is business_type='both' and its ZAR float is pre-funded.
    await _seed_p2p_config(db_session, test_tenant.id)
    await _seed_first_time_p2p_points_rule(db_session, test_tenant, reward_value=Decimal("50"))

    # Sender needs a points account so the reward CREDIT has somewhere to land.
    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 7771", with_points=True
    )
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
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 7772"},
            "amount": "100",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # The transfer landed to Bob, and the sender's points are surfaced inline.
    assert body["recipient_user_id"] == str(bob.id)
    assert body["earned_points"] == 50

    # A reward_events row was issued to the SENDER (the acting/debited user).
    assert await _reward_event_count(db_session, alice.id) == 1
    reward = (
        await db_session.execute(select(RewardEvent).where(RewardEvent.user_id == alice.id))
    ).scalar_one()
    assert reward.reward_type == "points"
    assert reward.reward_value == Decimal("50")
    # Never the passive recipient.
    assert await _reward_event_count(db_session, bob.id) == 0


@pytest.mark.asyncio
async def test_p2p_earned_points_reflects_active_bonus_multiplier(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a 2x bonus makes the sender earn — and see — double the base points.

    When a bonus multiplier is active, `issue_points_reward` credits the
    MULTIPLIED value to the ledger. The inline `earned_points` (and the
    RewardEvent it mirrors) must report that actual credited amount, not the
    rule's pre-multiplier base — otherwise the celebration understates reality.
    """
    from app.shared.models import BonusMultiplier

    await _seed_p2p_config(db_session, test_tenant.id)
    await _seed_first_time_p2p_points_rule(db_session, test_tenant, reward_value=Decimal("50"))
    # A business-wide 2x bonus → every points reward is doubled (base 50 → 100).
    db_session.add(BonusMultiplier(tenant_id=test_tenant.id, multiplier=Decimal("2.00")))
    await db_session.commit()

    alice, _ = await _make_user_with_wallet(
        db_session, test_tenant, phone="+27 82 555 7781", with_points=True
    )
    await _make_user_with_wallet(db_session, test_tenant, phone="+27 82 555 7782")
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
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 82 555 7782"},
            "amount": "100",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text

    # earned_points reflects the MULTIPLIED credit (50 base * 2), not the base.
    assert response.json()["earned_points"] == 100

    # And it equals the actual credited amount on the RewardEvent that hit the ledger.
    reward = (
        await db_session.execute(select(RewardEvent).where(RewardEvent.user_id == alice.id))
    ).scalar_one()
    assert reward.reward_value == Decimal("100")
    assert reward.multiplier_applied == Decimal("2.00")


@pytest.mark.asyncio
async def test_p2p_in_wallet_mode_earns_no_points(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant_factory,
) -> None:
    """Verify a wallet-only deployment never rewards a transfer (mode gate holds).

    Even with an active rule seeded, a `wallet`-mode tenant writes no reward
    outbox row, issues no reward, and returns `earned_points` 0 — proving the
    business_type gate holds all the way through the API response.
    """
    wallet_tenant = await tenant_factory(business_type="wallet")
    # Fund-via-float needs a pre-funded float even in wallet mode.
    await prefund_float(db_session, wallet_tenant.id, currency="ZAR")
    await _seed_p2p_config(db_session, wallet_tenant.id)
    # Seed a rule that WOULD fire in 'both' mode — its non-effect is the point.
    await _seed_first_time_p2p_points_rule(db_session, wallet_tenant, reward_value=Decimal("50"))

    alice, _ = await _make_user_with_wallet(
        db_session, wallet_tenant, phone="+27 83 555 3331", with_points=True
    )
    await _make_user_with_wallet(db_session, wallet_tenant, phone="+27 83 555 3332")
    await fund(
        db_session,
        tenant_id=wallet_tenant.id,
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
            "recipient": {"identifier_type": "phone", "identifier_value": "+27 83 555 3332"},
            "amount": "100",
            "currency": "ZAR",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["earned_points"] == 0

    # No reward was issued to anyone in this tenant.
    assert await _reward_event_count(db_session, alice.id) == 0
