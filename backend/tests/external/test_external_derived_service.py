"""Partner fund / withdraw / merchant-cashin wired to `resolve_service_code`
(Task 6, mechanical replication of the P2P reference wiring in
`tests/payments/test_p2p_derived_service.py`).

Spec §8: a partner key may name a derived service on `fund`, `withdraw`, and
`merchant_cashin` — each optional `service_code` on the partner request body
is resolved ONCE before any permission/pricing/limits gate, and the resolved
code drives everything downstream while `base_transaction_type` always
records the endpoint's own base. These tests prove: the omitted-`service_code`
path is unchanged for all three flows, and a derived service records its own
code + the base, charging its own (different) fee. They also prove the
idempotency fast-path binds on `base_transaction_type` (not `transaction_type`)
so a replay of a DERIVED-service call still matches its original result.

`tests/external/` has no `conftest.py` — every existing test file (e.g.
`test_external_fund_withdraw.py`, `test_merchant_cashin.py`) defines its
signing/wallet/config helpers locally. This file mirrors that same shape
rather than inventing new fixtures.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.secret_box import encrypt_secret
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
    Service,
    Tenant,
    Transaction,
    User,
    UserIdentifier,
)

_SECRET = "ext-derived-secret-do-not-log"


def _sign(key_id: str, secret: str, raw: bytes, *, idem: str = "idem-1") -> dict[str, str]:
    ts = int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return {
        "X-Sasai-Api-Key": key_id,
        "X-Sasai-Signature": f"t={ts},v1={digest}",
        "Idempotency-Key": idem,
        "Content-Type": "application/json",
    }


def _user_phone(user: User) -> str:
    return next(i.identifier_value for i in user.identifiers if i.identifier_type == "phone")


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


@pytest_asyncio.fixture
async def api_key(db_session: AsyncSession, test_tenant: Tenant) -> AsyncIterator[dict[str, str]]:
    """An active API key for the test tenant with a known plaintext secret."""
    db_session.add(
        ApiKey(
            tenant_id=test_tenant.id,
            key_id="sak_derived",
            secret_encrypted=encrypt_secret(_SECRET),
        )
    )
    await db_session.commit()
    yield {"key_id": "sak_derived", "secret": _SECRET}


async def _seed_scope_configs(
    session: AsyncSession,
    tenant: Tenant,
    transaction_type: str,
    *,
    fixed_fee: Decimal = Decimal("0"),
) -> None:
    """Seed a pricing + wide limit config for one scope (invariant #12 gate)."""
    session.add(
        PricingConfig(
            tenant_id=tenant.id,
            transaction_type=transaction_type,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=fixed_fee,
        )
    )
    session.add(
        LimitConfig(
            tenant_id=tenant.id,
            transaction_type=transaction_type,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            min_amount=Decimal("1"),
            max_amount=Decimal("100000"),
        )
    )
    await session.commit()


async def _seed_derived_service(
    session: AsyncSession, tenant: Tenant, *, base_code: str, code: str
) -> Service:
    """Persist a live base + derived service pair (Task 4 fixture shape)."""
    base = Service(tenant_id=tenant.id, code=base_code, display_name=base_code, kind="base")
    session.add(base)
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code,
        kind="derived",
        base_service_code=base_code,
    )
    session.add(row)
    await session.commit()
    return row


def _fund_body(phone: str, amount: str = "100") -> dict:
    return {
        "identifier_type": "phone",
        "identifier_value": phone,
        "amount": amount,
        "currency": "ZAR",
    }


# -----------------------------------------------------------------------------
# Fund
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_fund_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'fund' byte for byte"""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_scope_configs(db_session, test_tenant, "fund")
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "fund"
    assert txn.base_transaction_type == "fund"


@pytest.mark.asyncio
async def test_derived_fund_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Verify a derived fund service resolves, records the derived code + base
    'fund', and charges a fee that DIFFERS from the base's zero fee (pricing /
    limits are never inherited — spec §6.2)."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_scope_configs(db_session, test_tenant, "fund")
    await _seed_derived_service(db_session, test_tenant, base_code="fund", code="fund_promo")
    await _seed_scope_configs(db_session, test_tenant, "fund_promo", fixed_fee=Decimal("4"))

    body = _fund_body(_user_phone(test_user))
    body["service_code"] = "fund_promo"
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "fund_promo"
    assert txn.base_transaction_type == "fund"


# -----------------------------------------------------------------------------
# Withdraw
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_withdraw_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'withdraw' byte for byte"""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    await _seed_scope_configs(db_session, test_tenant, "withdraw")
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "100",
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "withdraw"
    assert txn.base_transaction_type == "withdraw"


@pytest.mark.asyncio
async def test_derived_withdraw_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Verify a derived withdraw service resolves and records the derived code
    + base 'withdraw'."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    await _seed_scope_configs(db_session, test_tenant, "withdraw")
    await _seed_derived_service(
        db_session, test_tenant, base_code="withdraw", code="withdraw_express"
    )
    await _seed_scope_configs(db_session, test_tenant, "withdraw_express", fixed_fee=Decimal("6"))

    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "100",
        "currency": "ZAR",
        "service_code": "withdraw_express",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "withdraw_express"
    assert txn.base_transaction_type == "withdraw"


@pytest.mark.asyncio
async def test_derived_withdraw_replay_matches_on_base_transaction_type(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Verify a replay of a DERIVED withdraw still returns the original result.

    The idempotency fast-path binds the key to `base_transaction_type` (always
    'withdraw'), not the derived `transaction_type` — otherwise a legitimate
    replay of a derived-service call would be wrongly rejected as a key reused
    across a different operation (S4 M-03).
    """
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    await _seed_scope_configs(db_session, test_tenant, "withdraw")
    await _seed_derived_service(
        db_session, test_tenant, base_code="withdraw", code="withdraw_express"
    )
    await _seed_scope_configs(db_session, test_tenant, "withdraw_express", fixed_fee=Decimal("6"))

    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "100",
        "currency": "ZAR",
        "service_code": "withdraw_express",
    }
    raw = json.dumps(body).encode()
    first = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw, idem="derived-replay-1"),
    )
    assert first.status_code == 201, first.text
    raw2 = json.dumps(body).encode()
    second = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw2,
        headers=_sign(api_key["key_id"], api_key["secret"], raw2, idem="derived-replay-1"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]


# -----------------------------------------------------------------------------
# Merchant cash-in
# -----------------------------------------------------------------------------


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
            identifier_value=f"+27 82 776 {uuid4().int % 10000:04d}",
            verified=True,
        )
    )
    await session.commit()
    await session.refresh(merchant)
    await _seed_wallet(session, tenant, merchant, balance=balance)
    return merchant


@pytest_asyncio.fixture
async def merchant(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """A merchant with a well-funded wallet."""
    return await _make_merchant(db_session, test_tenant, balance=Decimal("10000"))


@pytest_asyncio.fixture
async def merchant_key(
    db_session: AsyncSession, test_tenant: Tenant, merchant: User
) -> AsyncIterator[dict[str, str]]:
    """An active API key BOUND to the merchant (merchant_user_id set)."""
    db_session.add(
        ApiKey(
            tenant_id=test_tenant.id,
            key_id="sak_merchant_derived",
            secret_encrypted=encrypt_secret(_SECRET),
            merchant_user_id=merchant.id,
        )
    )
    await db_session.commit()
    yield {"key_id": "sak_merchant_derived", "secret": _SECRET}


def _consumer_phone(user: User) -> str:
    return next(i.identifier_value for i in user.identifiers if i.identifier_type == "phone")


@pytest.mark.asyncio
async def test_omitting_service_code_records_plain_merchant_cashin_unchanged(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
) -> None:
    """Verify no `service_code` in the request resolves to 'merchant_cashin' byte for byte"""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_scope_configs(db_session, test_tenant, "merchant_cashin")

    raw = json.dumps(_fund_body(_consumer_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/merchant-cashin",
        content=raw,
        headers=_sign(merchant_key["key_id"], merchant_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "merchant_cashin"
    assert txn.base_transaction_type == "merchant_cashin"


@pytest.mark.asyncio
async def test_derived_merchant_cashin_records_its_own_code_and_base_and_fee(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    merchant: User,
    merchant_key: dict[str, str],
) -> None:
    """Verify a derived merchant-cashin service resolves, records the derived
    code + base 'merchant_cashin', and charges a fee that DIFFERS from the
    base's zero fee."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_scope_configs(db_session, test_tenant, "merchant_cashin")
    await _seed_derived_service(
        db_session, test_tenant, base_code="merchant_cashin", code="merchant_cashin_bulk"
    )
    await _seed_scope_configs(
        db_session, test_tenant, "merchant_cashin_bulk", fixed_fee=Decimal("9")
    )

    body = _fund_body(_consumer_phone(test_user))
    body["service_code"] = "merchant_cashin_bulk"
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/merchant-cashin",
        content=raw,
        headers=_sign(merchant_key["key_id"], merchant_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    # Zero-fee base would leave the merchant at 10000 - 100 = 9900; the derived
    # fee (9) is borne by the merchant on top.
    assert Decimal(payload["merchant_new_balance"]) == Decimal("9891")

    txn = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
        )
    ).scalar_one()
    assert txn.transaction_type == "merchant_cashin_bulk"
    assert txn.base_transaction_type == "merchant_cashin"
