"""Integration tests for the external partner fund/withdraw API (Epic 18 S2).

HMAC-signed, tenant derived from the API key, partner Idempotency-Key used as
the ledger transaction key (safe retries), type-aware limits enforced.
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
    Account,
    ApiKey,
    LimitConfig,
    Tenant,
    User,
)

_SECRET = "ext-treasury-secret-do-not-log"


@pytest_asyncio.fixture
async def api_key(db_session: AsyncSession, test_tenant: Tenant) -> AsyncIterator[dict[str, str]]:
    """An active API key for the test tenant with a known plaintext secret."""
    db_session.add(
        ApiKey(
            tenant_id=test_tenant.id,
            key_id="sak_live_treasury",
            secret_encrypted=encrypt_secret(_SECRET),
        )
    )
    await db_session.commit()
    yield {"key_id": "sak_live_treasury", "secret": _SECRET}


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
async def test_external_fund_credits_user_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """A signed fund credits the user's wallet in the key's tenant."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["new_balance"]) == Decimal("100")
    assert await derive_balance(db_session, wallet.id) == (Decimal("100"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_fund_missing_auth_rejected(
    async_client: AsyncClient, test_user: User, api_key: dict[str, str]
) -> None:
    """No API key / signature → 401."""
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers={"Idempotency-Key": "x", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_external_fund_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Replaying the same Idempotency-Key funds the wallet exactly once."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    first = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw, idem="dup"),
    )
    assert first.status_code == 201, first.text
    raw2 = json.dumps(_fund_body(_user_phone(test_user))).encode()
    second = await async_client.post(
        "/api/v1/external/fund",
        content=raw2,
        headers=_sign(api_key["key_id"], api_key["secret"], raw2, idem="dup"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    assert await derive_balance(db_session, wallet.id) == (Decimal("100"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_fund_unknown_user_in_key_tenant_404(
    async_client: AsyncClient,
    other_tenant: Tenant,
    db_session: AsyncSession,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """The key scopes the tenant: a user that exists only in ANOTHER tenant
    doesn't resolve → 404 (tenant isolation via the key)."""
    # test_user belongs to test_tenant; the key is for test_tenant, but we ask
    # for a phone that isn't registered there.
    raw = json.dumps(_fund_body("+27829999999")).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------------
# Withdraw
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_withdraw_debits_user_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """A signed withdraw debits the user's wallet."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "200",
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["new_balance"]) == Decimal("300")


@pytest.mark.asyncio
async def test_external_withdraw_all_empties_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """withdraw_all with no amount pulls the full balance."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "withdraw_all": True,
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["amount"]) == Decimal("500")
    assert Decimal(resp.json()["new_balance"]) == Decimal("0")


@pytest.mark.asyncio
async def test_external_withdraw_insufficient_funds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Withdrawing more than the balance → 409."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("100"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "500",
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_external_withdraw_bad_signature_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Signature computed with the wrong secret → 401."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("100"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "10",
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], "the-wrong-secret", raw),
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_external_withdraw_amount_and_all_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Both amount and withdraw_all → 422 (schema)."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("100"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "10",
        "withdraw_all": True,
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_external_withdraw_idempotent_replay(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Replaying the same key withdraws exactly once, even though the first
    withdraw is now in the rolling total."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "200",
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    first = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw, idem="w-dup"),
    )
    assert first.status_code == 201, first.text
    raw2 = json.dumps(body).encode()
    second = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw2,
        headers=_sign(api_key["key_id"], api_key["secret"], raw2, idem="w-dup"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["transaction_id"] == first.json()["transaction_id"]
    assert await derive_balance(db_session, wallet.id) == (Decimal("300"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_withdraw_enforces_type_aware_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """A configured max_amount on the 'withdraw' limit caps the partner."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    db_session.add(
        LimitConfig(
            tenant_id=test_tenant.id,
            transaction_type="withdraw",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            max_amount=Decimal("150"),
        )
    )
    await db_session.commit()
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "200",
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/withdraw",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 422  # AmountAboveMax


@pytest.mark.asyncio
async def test_external_reused_key_across_ops_conflicts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """An Idempotency-Key used for fund cannot be reused for withdraw (S4 M-03)."""
    await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    fund_raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    fund = await async_client.post(
        "/api/v1/external/fund",
        content=fund_raw,
        headers=_sign(api_key["key_id"], api_key["secret"], fund_raw, idem="shared-key"),
    )
    assert fund.status_code == 201, fund.text

    wd_body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "50",
        "currency": "ZAR",
    }
    wd_raw = json.dumps(wd_body).encode()
    wd = await async_client.post(
        "/api/v1/external/withdraw",
        content=wd_raw,
        headers=_sign(api_key["key_id"], api_key["secret"], wd_raw, idem="shared-key"),
    )
    assert wd.status_code == 409
