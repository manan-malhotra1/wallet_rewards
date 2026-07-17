"""Signup-trigger referral behaviour through identity.create_user (WAL-77).

Exercises the end-to-end attribution flow: code generation on every signup,
pending-referral creation when a valid code is quoted, rejection of
unknown / self codes, and the referrer reward firing after create commits.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.shared.exceptions import InvalidReferralCode, SelfReferralNotAllowed
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Referral,
    ReferralCode,
    Rule,
    Tenant,
    User,
)


async def _create_user(
    session: AsyncSession, tenant_id, *, referral_code: str | None = None
) -> User:
    """Create a user via the service with one unique phone identifier."""
    req = CreateUserRequest(
        tenant_id=tenant_id,
        identifiers=[
            IdentifierIn(
                identifier_type="phone",
                identifier_value=f"+27 82 {uuid4().int % 10_000_000:07d}",
            )
        ],
        referral_code=referral_code,
    )
    return await create_user(session, req)


async def _own_code(session: AsyncSession, user_id) -> str:
    """Fetch the user's generated referral code."""
    row = (
        await session.execute(select(ReferralCode).where(ReferralCode.user_id == user_id))
    ).scalar_one()
    return row.code


async def _seed_points_infra(session: AsyncSession, tenant: Tenant, user: User) -> None:
    """Add the tenant system_points_issuance + the user's points account."""
    session.add(
        Account(
            tenant_id=tenant.id,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
        )
    )
    session.add(
        Account(
            tenant_id=tenant.id,
            user_id=user.id,
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_signup_with_valid_code_rewards_referrer(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A valid code at signup creates a rewarded referral + credits the referrer."""
    referrer = await _create_user(db_session, test_tenant.id)
    await _seed_points_infra(db_session, test_tenant, referrer)

    # Points system account is shared; referrer already has a points account.
    db_session.add(
        Rule(
            tenant_id=test_tenant.id,
            name="invite a friend",
            rule_type="referral",
            referral_trigger="signup",
            reward_type="points",
            reward_value=Decimal("50"),
            status="active",
        )
    )
    await db_session.commit()

    code = await _own_code(db_session, referrer.id)
    referee = await _create_user(db_session, test_tenant.id, referral_code=code)

    referral = (
        await db_session.execute(
            select(Referral).where(Referral.referred_user_id == referee.id)
        )
    ).scalar_one()
    assert referral.referrer_user_id == referrer.id
    assert referral.status == "rewarded"
    assert referral.referrer_rewarded_at is not None
    assert referral.referee_rewarded_at is None  # no referee reward configured

    referrer_points = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == referrer.id,
                Account.account_type == ACCOUNT_TYPE_POINTS,
            )
        )
    ).scalar_one()
    balance, _ = await derive_balance(db_session, referrer_points.id)
    assert balance == Decimal("50")


@pytest.mark.asyncio
async def test_organic_signup_creates_no_referral_but_generates_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """No code quoted → no referral row, yet the user still gets a unique code."""
    user = await _create_user(db_session, test_tenant.id)

    referrals = (
        (await db_session.execute(select(Referral).where(Referral.referred_user_id == user.id)))
        .scalars()
        .all()
    )
    assert referrals == []

    codes = (
        (await db_session.execute(select(ReferralCode).where(ReferralCode.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(codes) == 1
    assert codes[0].code  # non-empty


@pytest.mark.asyncio
async def test_unknown_referral_code_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A code that resolves to nobody in the tenant is a 422."""
    with pytest.raises(InvalidReferralCode):
        await _create_user(db_session, test_tenant.id, referral_code="NOSUCHCD")


@pytest.mark.asyncio
async def test_self_referral_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quoting one's own (just-generated) code is a 422 self-referral."""
    # Force the generated code to a known value so the same value can be quoted.
    monkeypatch.setattr(
        "app.modules.identity.service._generate_referral_code_value",
        lambda: "SELFCODE",
    )
    with pytest.raises(SelfReferralNotAllowed):
        await _create_user(db_session, test_tenant.id, referral_code="SELFCODE")


async def _wallet_balance(session: AsyncSession, user_id) -> Decimal | None:
    """Return the user's ZAR financial_wallet balance, or None if no wallet."""
    wallet = (
        await session.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            )
        )
    ).scalar_one_or_none()
    if wallet is None:
        return None
    balance, _ = await derive_balance(session, wallet.id)
    return balance


@pytest.mark.asyncio
async def test_signup_cashback_provisions_and_credits_brand_new_referee(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A signup cashback rule provisions the wallets and pays BOTH sides.

    The headline "join -> 100 ZAR" case: a brand-new referee has no wallet yet,
    so the referral reward path must provision the financial_wallet for each
    rewarded side and land the cashback (invariant #11 corollary b — cap-exempt
    promo credit). Neither user is pre-provisioned here.
    """
    referrer = await _create_user(db_session, test_tenant.id)
    db_session.add(
        Rule(
            tenant_id=test_tenant.id,
            name="join bonus",
            rule_type="referral",
            referral_trigger="signup",
            reward_type="cashback",
            reward_value=Decimal("50"),  # referrer
            referee_reward_value=Decimal("100"),  # referee (the new joiner)
            status="active",
        )
    )
    await db_session.commit()

    # Neither side has a wallet before the referral fires.
    assert await _wallet_balance(db_session, referrer.id) is None

    code = await _own_code(db_session, referrer.id)
    referee = await _create_user(db_session, test_tenant.id, referral_code=code)

    referral = (
        await db_session.execute(select(Referral).where(Referral.referred_user_id == referee.id))
    ).scalar_one()
    assert referral.status == "rewarded"
    assert referral.referrer_rewarded_at is not None
    assert referral.referee_rewarded_at is not None

    # Both wallets were auto-provisioned and credited from system_cash_inflow.
    assert await _wallet_balance(db_session, referrer.id) == Decimal("50")
    assert await _wallet_balance(db_session, referee.id) == Decimal("100")
