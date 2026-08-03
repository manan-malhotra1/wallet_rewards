"""Referral capture at mobile signup via `POST /identity/otp/send`.

Auto-registration of an unknown phone (Pay-PRD-0010) now accepts an optional
referrer's `referral_code`, so a NEW user is created WITH the code — creating
the `referrals` link and firing any active signup-trigger referral rule. Covers:

  - valid code on a NEW phone → referral row links referred -> referrer, and the
    seeded both-sided signup rule pays both sides.
  - invalid code on a NEW phone → 422 invalid_referral_code, and NO user created
    (create_user is atomic — the referral validation rolls the signup back).
  - a code on an EXISTING phone → 202, ignored (no new referral, no error).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Account, Referral, ReferralCode, Rule, Tenant, User, UserIdentifier
from app.shared.utils.normalize import normalize_phone
from tests.conftest import reward_event_count


async def _seed_referrer(
    session: AsyncSession, tenant: Tenant, *, code: str = "FRIEND1"
) -> User:
    """Create a referrer user owning a known referral code in the tenant."""
    referrer = User(tenant_id=tenant.id)
    session.add(referrer)
    await session.flush()
    session.add(ReferralCode(tenant_id=tenant.id, user_id=referrer.id, code=code))
    await session.commit()
    await session.refresh(referrer)
    return referrer


async def _seed_signup_referral_rule(session: AsyncSession, tenant: Tenant) -> Rule:
    """Seed an ACTIVE both-sided signup-trigger referral points rule."""
    from decimal import Decimal

    rule = Rule(
        tenant_id=tenant.id,
        name="invite a friend",
        rule_type="referral",
        referral_trigger="signup",
        reward_type="points",
        reward_value=Decimal("200"),  # referrer
        referee_reward_value=Decimal("200"),  # referee
        status="active",
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def _user_by_phone(session: AsyncSession, tenant: Tenant, phone: str) -> User | None:
    """Resolve the user owning `phone` (normalised) in the tenant, or None."""
    return (
        await session.execute(
            select(User)
            .join(UserIdentifier, UserIdentifier.user_id == User.id)
            .where(
                User.tenant_id == tenant.id,
                UserIdentifier.identifier_type == "phone",
                UserIdentifier.identifier_value == normalize_phone(phone),
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_otp_send_new_phone_with_valid_code_creates_referral_and_rewards(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
) -> None:
    """Verify signing up via OTP with a valid referral code links + rewards both sides."""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND1")
    await _seed_signup_referral_rule(db_session, test_tenant)

    phone = "+27 82 111 2223"
    response = await async_client.post(
        "/api/v1/identity/otp/send",
        json={"tenant_id": str(test_tenant.id), "phone": phone, "referral_code": "FRIEND1"},
    )
    assert response.status_code == 202, response.text

    referee = await _user_by_phone(db_session, test_tenant, phone)
    assert referee is not None

    referral = (
        await db_session.execute(
            select(Referral).where(Referral.referred_user_id == referee.id)
        )
    ).scalar_one()
    assert referral.referrer_user_id == referrer.id
    assert referral.code == "FRIEND1"
    assert referral.status == "rewarded"

    # Both sides earned the seeded signup reward.
    assert await reward_event_count(db_session, referrer.id) == 1
    assert await reward_event_count(db_session, referee.id) == 1


@pytest.mark.asyncio
async def test_otp_send_new_phone_with_invalid_code_422_and_no_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify an unknown referral code at OTP signup is rejected and creates no user."""
    phone = "+27 82 111 9999"
    response = await async_client.post(
        "/api/v1/identity/otp/send",
        json={"tenant_id": str(test_tenant.id), "phone": phone, "referral_code": "NOSUCHCD"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "invalid_referral_code"

    # Atomicity: the bad code rolled the signup back — no half-created user.
    assert await _user_by_phone(db_session, test_tenant, phone) is None


@pytest.mark.asyncio
async def test_otp_send_existing_phone_ignores_referral_code(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify an OTP re-request for an existing phone ignores a referral code entirely."""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND2")
    phone = f"+27 82 {uuid4().int % 10_000_000:07d}"

    # An already-registered phone (seeded directly — a single /otp/send call
    # keeps us clear of the 1/60s per-phone rate limit).
    existing = User(tenant_id=test_tenant.id)
    db_session.add(existing)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=existing.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=normalize_phone(phone),
            verified=True,
        )
    )
    await db_session.commit()

    # An OTP for the SAME phone quoting a code must not create a referral.
    response = await async_client.post(
        "/api/v1/identity/otp/send",
        json={"tenant_id": str(test_tenant.id), "phone": phone, "referral_code": "FRIEND2"},
    )
    assert response.status_code == 202, response.text

    referrals = (
        (
            await db_session.execute(
                select(Referral).where(Referral.referred_user_id == existing.id)
            )
        )
        .scalars()
        .all()
    )
    assert referrals == []
    # The referrer earned nothing from an ignored code.
    assert await reward_event_count(db_session, referrer.id) == 0
