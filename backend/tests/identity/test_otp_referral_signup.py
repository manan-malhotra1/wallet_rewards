"""Referral reward timing across the mobile OTP signup journey.

A referral reward is paid ONLY when a self-registered user COMPLETES signup —
i.e. the phone was OTP-verified AND the initial PIN is set. Quoting a valid
referrer code at `POST /identity/otp/send` creates a PENDING `referrals` link
(attribution only); the reward for BOTH sides fires later at `POST
/identity/pin/set`. This anti-farming timing means:

  - an unverified phone that never finishes signup is never paid;
  - admin-/externally-created users (which never run the self-reg PIN-set) are
    never rewarded and never even get a rewardable referral link;
  - a typo'd code is rejected at /otp/send BEFORE the per-phone OTP quota is
    consumed, so the phone is not locked out for the ~60s rate-limit window.

Dev OTPs are returned in the response body via `OTP_DEV_RETURN=true` in the test
config (same mechanism as `tests/identity/test_pin_otp_flow.py`).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.modules.rules.referral_evaluator import (
    evaluate_referral_on_registration_complete,
)
from app.shared.models import Account, Referral, ReferralCode, Rule, Tenant, User, UserIdentifier
from app.shared.utils.normalize import normalize_phone
from tests.conftest import reward_event_count

# -----------------------------------------------------------------------------
# Seed + flow helpers
# -----------------------------------------------------------------------------


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


async def _referral_for(session: AsyncSession, referred: User) -> Referral | None:
    """The single referral row where `referred` is the referred party, or None."""
    return (
        await session.execute(
            select(Referral).where(Referral.referred_user_id == referred.id)
        )
    ).scalar_one_or_none()


async def _send_otp(
    async_client: AsyncClient, tenant: Tenant, phone: str, *, referral_code: str | None = None
) -> Response:
    """POST /otp/send, optionally quoting a referrer code."""
    body: dict[str, str] = {"tenant_id": str(tenant.id), "phone": phone}
    if referral_code is not None:
        body["referral_code"] = referral_code
    return await async_client.post("/api/v1/identity/otp/send", json=body)


async def _verify_and_get_token(
    async_client: AsyncClient, tenant: Tenant, phone: str, otp: str
) -> str:
    """POST /otp/verify with the dev OTP, returning the registration token."""
    resp = await async_client.post(
        "/api/v1/identity/otp/verify",
        json={"tenant_id": str(tenant.id), "phone": phone, "otp": otp},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["registration_token"]


async def _set_initial_pin(async_client: AsyncClient, token: str, pin: str = "1234") -> None:
    """POST /pin/set to complete registration."""
    resp = await async_client.post(
        "/api/v1/identity/pin/set",
        json={"registration_token": token, "pin": pin},
    )
    assert resp.status_code == 204, resp.text


# -----------------------------------------------------------------------------
# 1 + 2. Reward fires only at PIN-set; pre-completion stages pay nothing.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_otp_send_then_verify_creates_pending_referral_but_pays_nothing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
) -> None:
    """Verify quoting a code and verifying the phone (no PIN yet) pays neither side"""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND1")
    await _seed_signup_referral_rule(db_session, test_tenant)

    phone = "+27 82 111 2223"
    send = await _send_otp(async_client, test_tenant, phone, referral_code="FRIEND1")
    assert send.status_code == 202, send.text

    # A PENDING referral links referred -> referrer immediately (attribution),
    # but no reward has been issued to anyone yet.
    referee = await _user_by_phone(db_session, test_tenant, phone)
    assert referee is not None
    referral = await _referral_for(db_session, referee)
    assert referral is not None
    assert referral.referrer_user_id == referrer.id
    assert referral.code == "FRIEND1"
    assert referral.status == "pending"
    assert await reward_event_count(db_session, referrer.id) == 0
    assert await reward_event_count(db_session, referee.id) == 0

    # Verifying the phone still does not complete registration → still no reward.
    otp = send.json()["otp"]
    await _verify_and_get_token(async_client, test_tenant, phone, otp)
    await db_session.refresh(referral)
    assert referral.status == "pending"
    assert await reward_event_count(db_session, referrer.id) == 0
    assert await reward_event_count(db_session, referee.id) == 0


@pytest.mark.asyncio
async def test_pin_set_completes_signup_and_rewards_both_sides(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
) -> None:
    """Verify setting the initial PIN completes signup and pays both sides once"""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND1")
    await _seed_signup_referral_rule(db_session, test_tenant)

    phone = "+27 82 111 3334"
    send = await _send_otp(async_client, test_tenant, phone, referral_code="FRIEND1")
    assert send.status_code == 202, send.text
    token = await _verify_and_get_token(async_client, test_tenant, phone, send.json()["otp"])

    await _set_initial_pin(async_client, token)

    referee = await _user_by_phone(db_session, test_tenant, phone)
    assert referee is not None
    referral = await _referral_for(db_session, referee)
    assert referral is not None
    assert referral.status == "rewarded"
    assert await reward_event_count(db_session, referrer.id) == 1
    assert await reward_event_count(db_session, referee.id) == 1


@pytest.mark.asyncio
async def test_incomplete_signup_without_pin_leaves_referral_pending(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
) -> None:
    """Verify a signup abandoned before the PIN step pays nobody and stays pending"""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND1")
    await _seed_signup_referral_rule(db_session, test_tenant)

    phone = "+27 82 111 4445"
    send = await _send_otp(async_client, test_tenant, phone, referral_code="FRIEND1")
    assert send.status_code == 202, send.text
    # Verify the phone but deliberately never set a PIN.
    await _verify_and_get_token(async_client, test_tenant, phone, send.json()["otp"])

    referee = await _user_by_phone(db_session, test_tenant, phone)
    assert referee is not None
    referral = await _referral_for(db_session, referee)
    assert referral is not None
    assert referral.status == "pending"
    assert await reward_event_count(db_session, referrer.id) == 0
    assert await reward_event_count(db_session, referee.id) == 0


# -----------------------------------------------------------------------------
# 3. Invalid code is rejected before the OTP quota is spent.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_code_422_creates_no_user_and_keeps_otp_quota(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify a bad referral code is rejected without a user or a burned OTP quota"""
    phone = "+27 82 111 5556"
    bad = await _send_otp(async_client, test_tenant, phone, referral_code="NOSUCHCD")
    assert bad.status_code == 422, bad.text
    assert bad.json()["error_code"] == "invalid_referral_code"
    assert await _user_by_phone(db_session, test_tenant, phone) is None

    # The quota was NOT consumed by the rejected attempt: a fresh /otp/send for
    # the SAME phone succeeds (202) rather than being rate-limited (429).
    retry = await _send_otp(async_client, test_tenant, phone)
    assert retry.status_code == 202, retry.text


# -----------------------------------------------------------------------------
# 4. A completed signup is paid at most once.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_completion_does_not_re_reward(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
) -> None:
    """Verify re-running registration-complete for a paid user pays nothing more"""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND1")
    await _seed_signup_referral_rule(db_session, test_tenant)

    phone = "+27 82 111 6667"
    send = await _send_otp(async_client, test_tenant, phone, referral_code="FRIEND1")
    token = await _verify_and_get_token(async_client, test_tenant, phone, send.json()["otp"])
    await _set_initial_pin(async_client, token)

    referee = await _user_by_phone(db_session, test_tenant, phone)
    assert referee is not None
    assert await reward_event_count(db_session, referrer.id) == 1
    assert await reward_event_count(db_session, referee.id) == 1

    # A later completion event (e.g. a PIN change re-triggering the hook) is a
    # no-op: the referral is no longer PENDING, so nobody is paid a second time.
    await evaluate_referral_on_registration_complete(
        db_session, tenant_id=test_tenant.id, referred_user_id=referee.id
    )
    assert await reward_event_count(db_session, referrer.id) == 1
    assert await reward_event_count(db_session, referee.id) == 1


# -----------------------------------------------------------------------------
# 5. Admin-/externally-created users never get a rewardable referral.
# -----------------------------------------------------------------------------


async def _admin_create_user(
    session: AsyncSession, tenant: Tenant, *, referral_code: str | None = None
) -> User:
    """Create a user via the admin path (self_registration defaults to False)."""
    request = CreateUserRequest(
        tenant_id=tenant.id,
        identifiers=[
            IdentifierIn(
                identifier_type="phone",
                identifier_value=f"+27 82 {uuid4().int % 10_000_000:07d}",
            )
        ],
        referral_code=referral_code,
    )
    return await create_user(session, request)


@pytest.mark.asyncio
async def test_admin_created_user_with_code_gets_no_referral_or_reward(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
) -> None:
    """Verify an admin-created user quoting a code earns nobody a referral reward"""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND1")
    await _seed_signup_referral_rule(db_session, test_tenant)

    created = await _admin_create_user(db_session, test_tenant, referral_code="FRIEND1")

    # The code is ignored: no rewardable referral link is minted at all.
    assert await _referral_for(db_session, created) is None
    assert await reward_event_count(db_session, referrer.id) == 0
    assert await reward_event_count(db_session, created.id) == 0


@pytest.mark.asyncio
async def test_admin_created_user_without_code_gets_no_referral_or_reward(
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify an admin-created user with no code has no referral and no reward"""
    created = await _admin_create_user(db_session, test_tenant)
    assert await _referral_for(db_session, created) is None
    assert await reward_event_count(db_session, created.id) == 0


# -----------------------------------------------------------------------------
# 6. An existing phone re-requesting an OTP ignores any quoted code.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_phone_otp_send_ignores_referral_code(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify an OTP re-request for an existing phone ignores a referral code"""
    referrer = await _seed_referrer(db_session, test_tenant, code="FRIEND2")
    phone = f"+27 82 {uuid4().int % 10_000_000:07d}"

    # Seed the phone as an already-registered user (a single /otp/send call keeps
    # us clear of the 1/60s per-phone rate limit).
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

    resp = await _send_otp(async_client, test_tenant, phone, referral_code="FRIEND2")
    assert resp.status_code == 202, resp.text

    assert await _referral_for(db_session, existing) is None
    assert await reward_event_count(db_session, referrer.id) == 0
