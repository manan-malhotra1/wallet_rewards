"""Changing a customer PIN.

POST /api/v1/pin/change: a user changes their own PIN — a charged self-service
operation subject to invariant #12 (fail-closed on BOTH pricing AND limit
config). Covers the fee and zero-fee happy paths, current-PIN verification with
login-grade lockout, the two invariant #12 fail-closed gates, idempotency, auth,
validation, insufficient funds, and NFR-0170 (no PIN/hash ever stored, audited,
or returned).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import verify_pin
from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_TAX_SERVICE,
    Account,
    AuditLog,
    PinChange,
    Tenant,
    Transaction,
    User,
)
from tests.pin_change.conftest import (
    CURRENT_PIN,
    NEW_PIN,
    change_pin_body,
    change_pin_headers,
)


async def _reload_pin_hash(session: AsyncSession, user_id) -> str | None:
    """Fetch the user's current pin_hash straight from the DB."""
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    await session.refresh(user)
    return user.pin_hash


async def _system_account(session: AsyncSession, tenant: Tenant, account_type: str) -> Account:
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == account_type,
                Account.currency == "ZAR",
                Account.user_id.is_(None),
            )
        )
    ).scalar_one()


# -----------------------------------------------------------------------------
# Happy path — fee > 0
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_with_fee_debits_wallet_and_switches_pin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    pin_user: User,
    pin_user_wallet: Account,
    fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a customer can change their PIN and is charged the fee"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert Decimal(data["fee"]) == Decimal("2")
    assert Decimal(data["tax"]) == Decimal("0.30")
    assert data["transaction_id"] is not None
    # NFR-0170: the response never echoes a PIN.
    assert "pin" not in {k.lower() for k in data}

    # New PIN authenticates; old PIN no longer does.
    pin_hash = await _reload_pin_hash(db_session, pin_user.id)
    assert pin_hash is not None
    assert verify_pin(NEW_PIN, pin_hash) is True
    assert verify_pin(CURRENT_PIN, pin_hash) is False

    # Wallet debited fee (2) + fee-tax (0.30): 100 -> 97.70.
    balance, _ = await derive_balance(db_session, pin_user_wallet.id)
    assert balance == Decimal("97.70")

    # Fee + service-tax landed in the system accounts.
    fee_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED)
    tax_acct = await _system_account(db_session, test_tenant, ACCOUNT_TYPE_TAX_SERVICE)
    assert (await derive_balance(db_session, fee_acct.id))[0] == Decimal("2")
    assert (await derive_balance(db_session, tax_acct.id))[0] == Decimal("0.30")

    # A Transaction + a PinChange row exist and are linked.
    pin_change = (
        await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id))
    ).scalar_one()
    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.transaction_type == "change_pin")
        )
    ).scalar_one()
    assert pin_change.transaction_id == txn.id


@pytest.mark.asyncio
async def test_change_pin_audit_row_has_no_pin_or_hash(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    pin_user_wallet: Account,
    fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a PIN change is audited without recording the PIN"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 200, resp.text

    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "pin.changed"))
    ).scalar_one()
    assert set(audit.after_state.keys()) == {"currency", "fee", "tax", "status", "transaction_id"}
    blob = json.dumps({"after": audit.after_state, "before": audit.before_state}).lower()
    assert "pin" not in blob
    assert "hash" not in blob
    assert CURRENT_PIN not in blob
    assert NEW_PIN not in blob


# -----------------------------------------------------------------------------
# Happy path — zero fee
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_zero_fee_writes_no_transaction(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    zero_fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a free PIN change moves no money"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["fee"]) == Decimal("0")
    assert data["transaction_id"] is None

    pin_hash = await _reload_pin_hash(db_session, pin_user.id)
    assert pin_hash is not None and verify_pin(NEW_PIN, pin_hash) is True

    pin_change = (
        await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id))
    ).scalar_one()
    assert pin_change.transaction_id is None
    txns = (
        (
            await db_session.execute(
                select(Transaction).where(Transaction.transaction_type == "change_pin")
            )
        )
        .scalars()
        .all()
    )
    assert txns == []


@pytest.mark.asyncio
async def test_change_pin_zero_fee_is_idempotent(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    zero_fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify repeating a free PIN change request changes the PIN only once"""
    headers = change_pin_headers(pin_auth_header, idem="zero-fee-replay")
    first = await async_client.post(
        "/api/v1/pin/change", content=json.dumps(change_pin_body()), headers=headers
    )
    second = await async_client.post(
        "/api/v1/pin/change", content=json.dumps(change_pin_body()), headers=headers
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    rows = (
        (await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


# -----------------------------------------------------------------------------
# Idempotency — fee path (one charge)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_fee_idempotent_charges_once(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    pin_user_wallet: Account,
    fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify repeating a charged PIN change request charges only once"""
    headers = change_pin_headers(pin_auth_header, idem="fee-replay")
    first = await async_client.post(
        "/api/v1/pin/change", content=json.dumps(change_pin_body()), headers=headers
    )
    second = await async_client.post(
        "/api/v1/pin/change", content=json.dumps(change_pin_body()), headers=headers
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()

    rows = (
        (await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    txns = (
        (
            await db_session.execute(
                select(Transaction).where(Transaction.transaction_type == "change_pin")
            )
        )
        .scalars()
        .all()
    )
    assert len(txns) == 1
    # Charged exactly once: 100 - 2.30 = 97.70 (not 95.40).
    balance, _ = await derive_balance(db_session, pin_user_wallet.id)
    assert balance == Decimal("97.70")


# -----------------------------------------------------------------------------
# Invariant #12 — fail-closed on BOTH pricing and limit (non-negotiable)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_fails_closed_when_pricing_config_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    limit_only_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a PIN change is refused when its pricing is not configured"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"

    # No PIN change persisted.
    pin_hash = await _reload_pin_hash(db_session, pin_user.id)
    assert pin_hash is not None and verify_pin(CURRENT_PIN, pin_hash) is True
    rows = (
        (await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id)))
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_change_pin_fails_closed_when_limit_config_missing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    pricing_only_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a PIN change is refused when its limits are not configured"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"

    pin_hash = await _reload_pin_hash(db_session, pin_user.id)
    assert pin_hash is not None and verify_pin(CURRENT_PIN, pin_hash) is True


# -----------------------------------------------------------------------------
# Current-PIN verification + lockout
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_wrong_current_pin_rejected_and_no_change(
    async_client: AsyncClient,
    db_session: AsyncSession,
    pin_user: User,
    zero_fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot change their PIN with the wrong current PIN"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body(current="0000")),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error_code"] == "invalid_credentials"

    pin_hash = await _reload_pin_hash(db_session, pin_user.id)
    assert pin_hash is not None and verify_pin(CURRENT_PIN, pin_hash) is True
    rows = (
        (await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id)))
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_change_pin_locks_out_after_repeated_wrong_current_pin(
    async_client: AsyncClient,
    pin_user: User,
    zero_fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify repeated wrong current PIN attempts lock the account"""
    last_status = None
    for i in range(5):
        resp = await async_client.post(
            "/api/v1/pin/change",
            content=json.dumps(change_pin_body(current="0000")),
            headers=change_pin_headers(pin_auth_header, idem=f"lock-{i}"),
        )
        last_status = resp.status_code
    # The 5th failure (PIN_MAX_ATTEMPTS) locks the account.
    assert last_status == 423
    # A correct PIN is now also refused while locked.
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header, idem="lock-after"),
    )
    assert resp.status_code == 423
    assert resp.json()["error_code"] == "account_locked"


# -----------------------------------------------------------------------------
# Auth + validation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_requires_authentication(async_client: AsyncClient) -> None:
    """Verify changing a PIN requires the customer to be signed in"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers={"Idempotency-Key": "noauth", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_pin_malformed_new_pin_rejected(
    async_client: AsyncClient,
    pin_user: User,
    zero_fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a new PIN that is not a valid format is rejected"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body(new="12ab")),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_pin_format"


@pytest.mark.asyncio
async def test_change_pin_new_same_as_current_rejected(
    async_client: AsyncClient,
    pin_user: User,
    zero_fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot reuse their current PIN as the new one"""
    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body(new=CURRENT_PIN)),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "new_pin_same_as_current"


# -----------------------------------------------------------------------------
# Insufficient funds for the fee
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_pin_insufficient_funds_for_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    pin_user: User,
    fee_configs: None,
    pin_auth_header: dict[str, str],
) -> None:
    """Verify a PIN change is refused when the wallet cannot cover the fee"""
    # An empty (unfunded) wallet so the fee can't be covered.
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=pin_user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(pin_auth_header),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "insufficient_funds"

    # Nothing committed — PIN still the old one, no PinChange row.
    pin_hash = await _reload_pin_hash(db_session, pin_user.id)
    assert pin_hash is not None and verify_pin(CURRENT_PIN, pin_hash) is True
    rows = (
        (await db_session.execute(select(PinChange).where(PinChange.user_id == pin_user.id)))
        .scalars()
        .all()
    )
    assert rows == []


async def _provision_tenant_user(
    session: AsyncSession, tenant: Tenant
) -> tuple[User, dict[str, str]]:
    """Create a ZAR consumer with the known current PIN + a session token, plus
    an explicit zero-fee change_pin pricing + limit config for `tenant`.

    Returns (user, auth_header). Zero-fee needs no wallet (no ledger legs).
    """
    from app.auth.hashing import hash_pin
    from app.auth.sessions import create_session
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config
    from app.shared.models import (
        ACCOUNT_TYPE_FINANCIAL_WALLET,
        USER_TYPE_CONSUMER,
        UserIdentifier,
    )

    user = User(tenant_id=tenant.id, user_type=USER_TYPE_CONSUMER, pin_hash=hash_pin(CURRENT_PIN))
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=f"+27 82 555 {tenant.id.hex[:4]}",
            verified=True,
        )
    )
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="change_pin",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
            fee_inclusive=False,
        ),
    )
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="change_pin",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await session.commit()
    token = await create_session(user.id, tenant.id, "mobile")
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_change_pin_is_tenant_isolated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Verify a reused key changes PINs independently across businesses

    The idempotency guard is `(tenant_id, idempotency_key)`, so a key used by a
    tenant-A user must not collide with — or leak the result of — a same-key
    request from a tenant-B user. Both succeed; each writes its own PinChange
    row scoped to its tenant.
    """
    other_tenant.base_currency = "ZAR"  # align with the ZAR change_pin configs
    db_session.add(other_tenant)
    await db_session.commit()

    user_a, auth_a = await _provision_tenant_user(db_session, test_tenant)
    user_b, auth_b = await _provision_tenant_user(db_session, other_tenant)

    shared_key = "pinchg-cross-tenant"
    resp_a = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(auth_a, idem=shared_key),
    )
    resp_b = await async_client.post(
        "/api/v1/pin/change",
        content=json.dumps(change_pin_body()),
        headers=change_pin_headers(auth_b, idem=shared_key),
    )
    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text

    # Two independent rows — one per tenant — despite the shared key.
    row_a = (
        (await db_session.execute(select(PinChange).where(PinChange.tenant_id == test_tenant.id)))
        .scalars()
        .all()
    )
    row_b = (
        (await db_session.execute(select(PinChange).where(PinChange.tenant_id == other_tenant.id)))
        .scalars()
        .all()
    )
    assert len(row_a) == 1 and row_a[0].user_id == user_a.id
    assert len(row_b) == 1 and row_b[0].user_id == user_b.id

    # Both users actually got the new PIN.
    for user in (user_a, user_b):
        pin_hash = await _reload_pin_hash(db_session, user.id)
        assert pin_hash is not None and verify_pin(NEW_PIN, pin_hash) is True
