"""Referral attribution at signup and reward at registration completion.

Exercises the two-stage flow: `create_user(self_registration=True)` mints a
shareable code on every signup and, when a valid code is quoted, a PENDING
`referrals` link (attribution) — but pays NOTHING at this point. The reward for
both sides fires only when the referred user COMPLETES registration
(`evaluate_referral_on_registration_complete`, invoked at PIN-set). Unknown /
self codes are still rejected at create time, before any commit.
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
from app.modules.rules.referral_evaluator import (
    evaluate_referral_on_registration_complete,
)
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
    session: AsyncSession,
    tenant_id,
    *,
    referral_code: str | None = None,
    self_registration: bool = True,
) -> User:
    """Create a user via the service with one unique phone identifier.

    Defaults to the self-registration path (`self_registration=True`) so a quoted
    `referral_code` mints the PENDING attribution link — that is the surface these
    tests exercise. Pass `self_registration=False` to model the admin path, which
    ignores the code entirely.
    """
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
    return await create_user(session, req, self_registration=self_registration)


async def _complete_registration(session: AsyncSession, referee: User) -> None:
    """Fire the completion hook that `set_pin` runs once the initial PIN lands."""
    await evaluate_referral_on_registration_complete(
        session, tenant_id=referee.tenant_id, referred_user_id=referee.id
    )


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
async def test_completed_signup_with_valid_code_rewards_referrer(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a referred user who completes registration rewards the referrer"""
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
        await db_session.execute(select(Referral).where(Referral.referred_user_id == referee.id))
    ).scalar_one()
    # Attribution only at create — nobody is paid until registration completes.
    assert referral.referrer_user_id == referrer.id
    assert referral.status == "pending"
    assert referral.referrer_rewarded_at is None

    # Completing registration (PIN-set hook) is what pays the referrer.
    await _complete_registration(db_session, referee)
    await db_session.refresh(referral)
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
    """Verify a customer who signs up without a code still gets their own referral code"""
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
    """Verify signing up with an unrecognized referral code is rejected"""
    with pytest.raises(InvalidReferralCode):
        await _create_user(db_session, test_tenant.id, referral_code="NOSUCHCD")


@pytest.mark.asyncio
async def test_self_referral_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a customer cannot refer themselves"""
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
    """Verify a signup cashback referral opens wallets and pays both sides

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

    # No cashback until the referred user completes registration.
    referral = (
        await db_session.execute(select(Referral).where(Referral.referred_user_id == referee.id))
    ).scalar_one()
    assert referral.status == "pending"
    assert await _wallet_balance(db_session, referee.id) is None

    await _complete_registration(db_session, referee)
    await db_session.refresh(referral)
    assert referral.status == "rewarded"
    assert referral.referrer_rewarded_at is not None
    assert referral.referee_rewarded_at is not None

    # Both wallets were auto-provisioned and credited from system_cash_inflow.
    assert await _wallet_balance(db_session, referrer.id) == Decimal("50")
    assert await _wallet_balance(db_session, referee.id) == Decimal("100")


@pytest.mark.asyncio
async def test_create_does_not_issue_reward_even_if_reward_backend_is_down(
    db_session: AsyncSession, test_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify signup itself never touches reward issuance — it only attributes

    Reward issuance is fully decoupled from `create_user` now: a quoted code
    mints a PENDING referral and nothing else. So even with the reward path
    hard-wired to explode, signup succeeds and the referral is left PENDING for
    the completion hook to pay (or a reconciliation job to retry) later.
    """
    referrer = await _create_user(db_session, test_tenant.id)
    code = await _own_code(db_session, referrer.id)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("reward backend down")

    # If create_user still called the evaluator, this would blow the signup up.
    monkeypatch.setattr("app.modules.rules.referral_evaluator.evaluate_referral_on_signup", _boom)

    referee = await _create_user(db_session, test_tenant.id, referral_code=code)

    # Signup succeeded — the user exists.
    assert referee.id is not None
    persisted = (await db_session.execute(select(User).where(User.id == referee.id))).scalar_one()
    assert persisted.id == referee.id

    # The referral is durable but left PENDING (unrewarded), reconcilable later.
    referral = (
        await db_session.execute(select(Referral).where(Referral.referred_user_id == referee.id))
    ).scalar_one()
    assert referral.status == "pending"
    assert referral.referrer_rewarded_at is None
