"""Account lock enforcement — what a locked customer can and cannot do.

Two enforcement points that used to be COSMETIC and are now real:

  1. Login — `authenticate_pin` rejects a `suspended` / `closed` account (403
     account_suspended) BEFORE PIN verification; `txn_locked` and `active` may
     log in.
  2. Transactions — `assert_user_can_transact` blocks every user-initiated money
     path (403 transactions_blocked) when the initiator's status != active. The
     guard runs AFTER the idempotency fast-path (replays still return the
     original) and BEFORE any charge/ledger work. Receiving is passive and NOT
     blocked.

Regression focus: a previously-cosmetic `suspended` now actually blocks both
login and transactions.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cashout.schemas import CashOutRequest
from app.modules.cashout.service import cash_out
from app.modules.identity.service import assert_user_can_transact
from app.modules.payments.service import p2p_transfer
from app.modules.pin_change.schemas import ChangePinRequest
from app.modules.pin_change.service import change_pin
from app.shared.exceptions import TransactionsBlocked, UserNotFound
from app.shared.models import (
    USER_STATUS_CLOSED,
    USER_STATUS_SUSPENDED,
    USER_STATUS_TXN_LOCKED,
    PinChange,
    Role,
    RolePermission,
    Tenant,
    User,
    UserIdentifier,
)
from tests.conftest import TestSessionLocal

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _set_status(user_id, status: str) -> None:
    """Flip a user's status in the DB via a fresh committed session."""
    async with TestSessionLocal() as s:
        await s.execute(update(User).where(User.id == user_id).values(status=status))
        await s.commit()


async def _register_with_pin(async_client, tenant: Tenant, phone: str, pin: str = "1234") -> None:
    """Register a user via the OTP dev flow and set their PIN."""
    send = await async_client.post(
        "/api/v1/identity/otp/send",
        json={"tenant_id": str(tenant.id), "phone": phone},
    )
    otp = send.json()["otp"]
    verify = await async_client.post(
        "/api/v1/identity/otp/verify",
        json={"tenant_id": str(tenant.id), "phone": phone, "otp": otp},
    )
    reg_token = verify.json()["registration_token"]
    await async_client.post(
        "/api/v1/identity/pin/set",
        json={"registration_token": reg_token, "pin": pin},
    )


async def _phone_user_id(session: AsyncSession, tenant: Tenant, phone_normalised: str):
    """Resolve the user_id behind a (tenant, phone) identifier."""
    row = (
        await session.execute(
            select(UserIdentifier.user_id).where(
                UserIdentifier.tenant_id == tenant.id,
                UserIdentifier.identifier_value == phone_normalised,
            )
        )
    ).scalar_one()
    return row


# =============================================================================
# assert_user_can_transact — the shared guard
# =============================================================================


@pytest.mark.asyncio
async def test_guard_allows_active_user(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify an active customer is allowed to transact"""
    await assert_user_can_transact(db_session, tenant_id=test_tenant.id, user_id=test_user.id)


@pytest.mark.parametrize(
    "status",
    [USER_STATUS_TXN_LOCKED, USER_STATUS_SUSPENDED, USER_STATUS_CLOSED],
)
@pytest.mark.asyncio
async def test_guard_blocks_non_active_user(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, status: str
) -> None:
    """Verify a locked or suspended customer cannot transact"""
    await _set_status(test_user.id, status)
    with pytest.raises(TransactionsBlocked):
        await assert_user_can_transact(db_session, tenant_id=test_tenant.id, user_id=test_user.id)


@pytest.mark.asyncio
async def test_guard_unknown_user_is_404(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a customer who does not exist cannot transact"""
    with pytest.raises(UserNotFound):
        await assert_user_can_transact(db_session, tenant_id=test_tenant.id, user_id=uuid4())


@pytest.mark.asyncio
async def test_guard_cross_tenant_is_404(
    db_session: AsyncSession, other_tenant: Tenant, test_user: User
) -> None:
    """Verify a customer from another tenant cannot transact"""
    with pytest.raises(UserNotFound):
        await assert_user_can_transact(db_session, tenant_id=other_tenant.id, user_id=test_user.id)


# =============================================================================
# Login enforcement — authenticate_pin
# =============================================================================


@pytest.mark.parametrize("status", [USER_STATUS_SUSPENDED, USER_STATUS_CLOSED])
@pytest.mark.asyncio
async def test_login_blocked_for_login_locked_status(
    async_client, db_session: AsyncSession, test_tenant: Tenant, status: str
) -> None:
    """Verify a suspended or closed customer cannot sign in"""
    phone = f"+27 82 511 {uuid4().int % 10000:04d}"
    await _register_with_pin(async_client, test_tenant, phone)
    user_id = await _phone_user_id(db_session, test_tenant, phone.replace(" ", ""))
    await _set_status(user_id, status)

    resp = await async_client.post(
        "/api/v1/identity/auth/pin",
        json={"tenant_id": str(test_tenant.id), "phone": phone, "pin": "1234"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "account_suspended"


@pytest.mark.asyncio
async def test_login_allowed_for_txn_locked(
    async_client, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a transactions-locked customer can still sign in to view their account"""
    phone = f"+27 82 512 {uuid4().int % 10000:04d}"
    await _register_with_pin(async_client, test_tenant, phone)
    user_id = await _phone_user_id(db_session, test_tenant, phone.replace(" ", ""))
    await _set_status(user_id, USER_STATUS_TXN_LOCKED)

    resp = await async_client.post(
        "/api/v1/identity/auth/pin",
        json={"tenant_id": str(test_tenant.id), "phone": phone, "pin": "1234"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["session_token"]


@pytest.mark.asyncio
async def test_login_allowed_for_active(async_client, test_tenant: Tenant) -> None:
    """Verify an active customer can sign in normally"""
    phone = f"+27 82 513 {uuid4().int % 10000:04d}"
    await _register_with_pin(async_client, test_tenant, phone)

    resp = await async_client.post(
        "/api/v1/identity/auth/pin",
        json={"tenant_id": str(test_tenant.id), "phone": phone, "pin": "1234"},
    )
    assert resp.status_code == 200, resp.text


# =============================================================================
# Transaction enforcement — money paths call the guard
# =============================================================================


async def _grant_role(session: AsyncSession, tenant: Tenant, user_id, txn_types: tuple[str, ...]):
    """Attach a role permitting the given transaction types to a user."""
    from app.shared.models import UserRole

    role = Role(tenant_id=tenant.id, name=f"role-{uuid4().hex[:8]}")
    session.add(role)
    await session.flush()
    for t in txn_types:
        session.add(RolePermission(role_id=role.id, transaction_type=t, permitted=True))
    session.add(UserRole(user_id=user_id, role_id=role.id))
    await session.commit()


@pytest.mark.parametrize("status", [USER_STATUS_TXN_LOCKED, USER_STATUS_SUSPENDED])
@pytest.mark.asyncio
async def test_p2p_send_blocked_for_locked_sender(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, status: str
) -> None:
    """Verify a locked customer cannot send money to another person"""
    await _set_status(test_user.id, status)
    with pytest.raises(TransactionsBlocked):
        await p2p_transfer(
            db_session,
            tenant_id=test_tenant.id,
            sender_user_id=test_user.id,
            recipient_identifier_type="phone",
            recipient_identifier_value="+27 82 555 0000",
            amount=Decimal("10"),
            currency="ZAR",
            idempotency_key=f"p2p-{uuid4().hex[:10]}",
        )


@pytest.mark.parametrize("status", [USER_STATUS_TXN_LOCKED, USER_STATUS_SUSPENDED])
@pytest.mark.asyncio
async def test_change_pin_blocked_for_locked_user(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, status: str
) -> None:
    """Verify a locked customer cannot change their PIN"""
    await _set_status(test_user.id, status)
    with pytest.raises(TransactionsBlocked):
        await change_pin(
            db_session,
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            request=ChangePinRequest(current_pin="1234", new_pin="5678", currency="ZAR"),
            idempotency_key=f"pinchg-{uuid4().hex[:10]}",
            principal=None,  # guard fires before the principal is used
        )


@pytest.mark.asyncio
async def test_cashout_blocked_for_locked_subscriber(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify a locked customer cannot cash out"""
    await _grant_role(db_session, test_tenant, test_user.id, ("cashout",))
    await _set_status(test_user.id, USER_STATUS_TXN_LOCKED)
    with pytest.raises(TransactionsBlocked):
        await cash_out(
            db_session,
            tenant_id=test_tenant.id,
            subscriber_user_id=test_user.id,
            request=CashOutRequest(
                identifier_type="phone",
                identifier_value="+27 82 555 0000",
                amount=Decimal("10"),
                currency="ZAR",
            ),
            idempotency_key=f"cashout-{uuid4().hex[:10]}",
        )


@pytest.mark.asyncio
async def test_guard_runs_after_idempotency_fast_path(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify a retried request returns the original result even after the customer is locked

    Proves the guard sits AFTER the idempotency fast-path: a pre-existing
    change_pin row is returned as-is rather than raising TransactionsBlocked.
    """
    key = f"pinchg-replay-{uuid4().hex[:8]}"
    original = PinChange(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        idempotency_key=key,
        currency="ZAR",
        fee_amount=Decimal("0"),
        tax_amount=Decimal("0"),
        status="completed",
    )
    db_session.add(original)
    await db_session.commit()

    await _set_status(test_user.id, USER_STATUS_TXN_LOCKED)

    result = await change_pin(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        request=ChangePinRequest(current_pin="1234", new_pin="5678", currency="ZAR"),
        idempotency_key=key,
        principal=None,
    )
    # The original row comes back (no TransactionsBlocked despite the lock).
    assert result.id == original.id
    assert result.status == "completed"
