"""Merchant cash-in to a customer.

A funded MERCHANT, authenticated by a merchant-bound API key, funds a CONSUMER
from the merchant's OWN wallet. HMAC-signed, tenant derived from the key, the
partner Idempotency-Key used as the ledger transaction key (safe retries).

Mirrors the external fund/withdraw test patterns (API-key signing helper etc.).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.secret_box import encrypt_secret
from app.modules.accounts.service import derive_balance
from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    USER_TYPE_MERCHANT,
    Account,
    ApiKey,
    LimitConfig,
    PricingConfig,
    Tenant,
    User,
    UserIdentifier,
)

_SECRET = "ext-merchant-secret-do-not-log"
_SERVICE = "merchant_cashin"


async def _seed_service_configs(
    session: AsyncSession,
    tenant: Tenant,
    *,
    with_pricing: bool = True,
    with_limit: bool = True,
) -> None:
    """Seed a zero-fee pricing config and/or a wide limit config (user_type=NULL).

    The fail-closed gate (invariant #12) needs BOTH to resolve for the merchant's
    type before the money path may run. `with_pricing` / `with_limit` let a test
    seed only one side to prove the gate fails closed when the OTHER is missing.
    """
    if with_pricing:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type=_SERVICE,
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("0"),
            )
        )
    if with_limit:
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type=_SERVICE,
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                min_amount=Decimal("1"),
                max_amount=Decimal("100000"),
            )
        )
    await session.commit()


async def _seed_wallet(
    session: AsyncSession, tenant: Tenant, user: User, *, balance: Decimal
) -> Account:
    """Create the user's ZAR wallet; fund it with `balance` when > 0."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(wallet)
    if balance > 0:
        # One system_cash_inflow per (tenant, currency) — reuse if a prior
        # _seed_wallet already created it (uq_accounts_system_scoped).
        inflow = (
            await session.execute(
                select(Account).where(
                    Account.tenant_id == tenant.id,
                    Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
                    Account.currency == "ZAR",
                    Account.user_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if inflow is None:
            inflow = Account(
                tenant_id=tenant.id, account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW, currency="ZAR"
            )
            session.add(inflow)
            await session.flush()
        await post_transaction(
            session,
            PostTransactionRequest(
                tenant_id=tenant.id,
                idempotency_key=f"seed-{uuid4().hex}",
                transaction_type="bootstrap",
                currency="ZAR",
                amount=balance,
                entries=[
                    LedgerEntryRequest(account_id=inflow.id, entry_type="DEBIT", amount=balance),
                    LedgerEntryRequest(account_id=wallet.id, entry_type="CREDIT", amount=balance),
                ],
            ),
        )
    return wallet


async def _make_merchant(session: AsyncSession, tenant: Tenant, *, balance: Decimal) -> User:
    """Create a merchant user with a phone identifier and a funded ZAR wallet."""
    merchant = User(tenant_id=tenant.id, user_type=USER_TYPE_MERCHANT)
    session.add(merchant)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=merchant.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=f"+27 82 777 {uuid4().int % 10000:04d}",
            verified=True,
        )
    )
    await session.commit()
    await session.refresh(merchant)
    await _seed_wallet(session, tenant, merchant, balance=balance)
    return merchant


@pytest_asyncio.fixture
async def merchant(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """A merchant with a well-funded wallet (the default funding source)."""
    return await _make_merchant(db_session, test_tenant, balance=Decimal("10000"))


@pytest_asyncio.fixture
async def merchant_key(
    db_session: AsyncSession, test_tenant: Tenant, merchant: User
) -> AsyncIterator[dict[str, str]]:
    """An active API key BOUND to the merchant (merchant_user_id set)."""
    db_session.add(
        ApiKey(
            tenant_id=test_tenant.id,
            key_id="sak_merchant",
            secret_encrypted=encrypt_secret(_SECRET),
            merchant_user_id=merchant.id,
        )
    )
    await db_session.commit()
    yield {"key_id": "sak_merchant", "secret": _SECRET}


@pytest_asyncio.fixture
async def plain_key(db_session: AsyncSession, test_tenant: Tenant) -> AsyncIterator[dict[str, str]]:
    """An active API key with NO merchant binding (ordinary partner key)."""
    db_session.add(
        ApiKey(
            tenant_id=test_tenant.id,
            key_id="sak_plain",
            secret_encrypted=encrypt_secret(_SECRET),
        )
    )
    await db_session.commit()
    yield {"key_id": "sak_plain", "secret": _SECRET}


@pytest_asyncio.fixture
async def configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Both pricing + limit configs so the gate passes for transacting tests."""
    await _seed_service_configs(db_session, test_tenant)


def _sign(key_id: str, secret: str, raw: bytes, *, idem: str = "idem-1") -> dict[str, str]:
    ts = int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return {
        "X-Sasai-Api-Key": key_id,
        "X-Sasai-Signature": f"t={ts},v1={digest}",
        "Idempotency-Key": idem,
        "Content-Type": "application/json",
    }


def _consumer_phone(user: User) -> str:
    return next(i.identifier_value for i in user.identifiers if i.identifier_type == "phone")


def _body(phone: str, amount: str = "100") -> dict:
    return {
        "identifier_type": "phone",
        "identifier_value": phone,
        "amount": amount,
        "currency": "ZAR",
    }


async def _post(client: AsyncClient, key: dict[str, str], body: dict, *, idem: str = "idem-1"):
    raw = json.dumps(body).encode()
    return await client.post(
        "/api/v1/external/merchant-cashin",
        content=raw,
        headers=_sign(key["key_id"], key["secret"], raw, idem=idem),
    )


# -----------------------------------------------------------------------------
# Happy path
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merchant_funds_consumer_moves_money(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
    configs: None,
) -> None:
    """Verify a merchant can cash a customer in from the merchant's own wallet"""
    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    merchant_wallet = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == merchant.id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            )
        )
    ).scalar_one()

    resp = await _post(async_client, merchant_key, _body(_consumer_phone(test_user), "100"))
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert Decimal(payload["consumer_new_balance"]) == Decimal("100")
    # Zero-fee config → merchant debited exactly the principal.
    assert Decimal(payload["merchant_new_balance"]) == Decimal("9900")

    # Ledger reflects it.
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("100"), Decimal("0"))
    assert await derive_balance(db_session, merchant_wallet.id) == (Decimal("9900"), Decimal("0"))


@pytest.mark.asyncio
async def test_merchant_cashin_debit_includes_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
) -> None:
    """Verify a cash-in fee is borne by the merchant and not the customer"""
    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    # R5 flat fee (exclusive by default) + wide limit.
    db_session.add(
        PricingConfig(
            tenant_id=test_tenant.id,
            transaction_type=_SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("5"),
        )
    )
    db_session.add(
        LimitConfig(
            tenant_id=test_tenant.id,
            transaction_type=_SERVICE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            min_amount=Decimal("1"),
            max_amount=Decimal("100000"),
        )
    )
    await db_session.commit()

    resp = await _post(async_client, merchant_key, _body(_consumer_phone(test_user), "100"))
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert Decimal(payload["consumer_new_balance"]) == Decimal("100")  # principal only
    assert Decimal(payload["merchant_new_balance"]) == Decimal("9895")  # 10000 - 100 - 5 fee
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("100"), Decimal("0"))


# -----------------------------------------------------------------------------
# Fail-closed service gate (invariant #12)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fails_closed_when_no_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
) -> None:
    """Verify a cash-in is refused when the service has no pricing or limit set up"""
    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    resp = await _post(async_client, merchant_key, _body(_consumer_phone(test_user)))
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("0"), Decimal("0"))


@pytest.mark.asyncio
async def test_fails_closed_when_only_pricing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
) -> None:
    """Verify a cash-in is refused when a limit is not set up"""
    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_service_configs(db_session, test_tenant, with_limit=False)
    resp = await _post(async_client, merchant_key, _body(_consumer_phone(test_user)))
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("0"), Decimal("0"))


@pytest.mark.asyncio
async def test_fails_closed_when_only_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
) -> None:
    """Verify a cash-in is refused when pricing is not set up"""
    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_service_configs(db_session, test_tenant, with_pricing=False)
    resp = await _post(async_client, merchant_key, _body(_consumer_phone(test_user)))
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("0"), Decimal("0"))


# -----------------------------------------------------------------------------
# Balance guard — funded-merchant requirement (invariant #11)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insufficient_merchant_funds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant_key: dict[str, str],
    configs: None,
) -> None:
    """Verify a merchant with too little balance cannot cash a customer in"""
    # This test overrides the default `merchant` fixture's wallet by binding the
    # key to a POORLY-funded merchant instead.
    poor = await _make_merchant(db_session, test_tenant, balance=Decimal("50"))
    # Re-bind the seeded merchant_key to the poorly-funded merchant.
    await db_session.execute(
        update(ApiKey).where(ApiKey.key_id == "sak_merchant").values(merchant_user_id=poor.id)
    )
    await db_session.commit()

    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    resp = await _post(async_client, merchant_key, _body(_consumer_phone(test_user), "500"))
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "insufficient_funds"
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("0"), Decimal("0"))


# -----------------------------------------------------------------------------
# Authorisation / validation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_merchant_key_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    plain_key: dict[str, str],
    configs: None,
) -> None:
    """Verify an ordinary partner key cannot perform a merchant cash-in"""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    resp = await _post(async_client, plain_key, _body(_consumer_phone(test_user)))
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "not_a_merchant_key"


@pytest.mark.asyncio
async def test_missing_auth_rejected(
    async_client: AsyncClient, test_user: User, merchant_key: dict[str, str]
) -> None:
    """Verify an unsigned cash-in request is rejected"""
    raw = json.dumps(_body(_consumer_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/merchant-cashin",
        content=raw,
        headers={"Idempotency-Key": "x", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bad_signature_rejected(
    async_client: AsyncClient, test_user: User, merchant_key: dict[str, str]
) -> None:
    """Verify a cash-in request with an invalid signature is rejected"""
    resp = await _post(
        async_client,
        {"key_id": merchant_key["key_id"], "secret": "the-wrong-secret"},
        _body(_consumer_phone(test_user)),
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected(
    async_client: AsyncClient, test_user: User, merchant_key: dict[str, str]
) -> None:
    """Verify a cash-in request without an idempotency key is rejected"""
    raw = json.dumps(_body(_consumer_phone(test_user))).encode()
    ts = int(time.time())
    digest = hmac.new(
        merchant_key["secret"].encode(), f"{ts}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    resp = await async_client.post(
        "/api/v1/external/merchant-cashin",
        content=raw,
        headers={
            "X-Sasai-Api-Key": merchant_key["key_id"],
            "X-Sasai-Signature": f"t={ts},v1={digest}",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_consumer_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    merchant: User,
    merchant_key: dict[str, str],
    configs: None,
) -> None:
    """Verify a cash-in to an unknown customer is rejected"""
    resp = await _post(async_client, merchant_key, _body("+27829999999"))
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Idempotency + tenant isolation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_replay_moves_once(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
    configs: None,
) -> None:
    """Verify replaying a cash-in credits the customer only once"""
    consumer_wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    body = _body(_consumer_phone(test_user), "100")
    first = await _post(async_client, merchant_key, body, idem="mc-dup")
    assert first.status_code == 201, first.text
    second = await _post(async_client, merchant_key, body, idem="mc-dup")
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    # Only one credit landed.
    assert await derive_balance(db_session, consumer_wallet.id) == (Decimal("100"), Decimal("0"))


@pytest.mark.asyncio
async def test_tenant_isolation_via_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    merchant: User,
    merchant_key: dict[str, str],
    configs: None,
) -> None:
    """Verify a merchant cannot cash in a customer from another tenant.

    The key scopes the tenant, so a merchant in test_tenant cannot reach a user
    registered in other_tenant.
    """
    other_user = User(tenant_id=other_tenant.id)
    db_session.add(other_user)
    await db_session.flush()
    phone = f"+27 82 888 {uuid4().int % 10000:04d}"
    db_session.add(
        UserIdentifier(
            user_id=other_user.id,
            tenant_id=other_tenant.id,
            identifier_type="phone",
            identifier_value=phone,
            verified=True,
        )
    )
    await db_session.commit()

    resp = await _post(async_client, merchant_key, _body(phone))
    assert resp.status_code == 404
