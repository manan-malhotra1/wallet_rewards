"""Integration tests for the external partner fund/withdraw API (Epic 18 S2).

HMAC-signed, tenant derived from the API key, partner Idempotency-Key used as
the ledger transaction key (safe retries), type-aware limits enforced.
"""

from __future__ import annotations

import asyncio
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
from sqlalchemy import case, func, select
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
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    Account,
    ApiKey,
    LedgerEntry,
    LimitConfig,
    PricingConfig,
    Tenant,
    User,
    WalletLimitConfig,
)

_SECRET = "ext-treasury-secret-do-not-log"


async def _seed_service_configs(
    session: AsyncSession,
    tenant: Tenant,
    *,
    service: str,
    with_pricing: bool = True,
    with_limit: bool = True,
) -> None:
    """Seed a zero-fee pricing config and/or a wide limit config for a scope.

    The fail-closed service gate (invariant #12) requires BOTH a pricing and a
    limit config to resolve for the acting user's type before a money path may
    run. These `user_type=NULL` defaults satisfy the gate for every user type.
    `with_pricing` / `with_limit` let a test seed only one side to prove the
    gate fails closed when the OTHER is missing.
    """
    if with_pricing:
        session.add(
            PricingConfig(
                tenant_id=tenant.id,
                transaction_type=service,
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                fixed_fee=Decimal("0"),
            )
        )
    if with_limit:
        session.add(
            LimitConfig(
                tenant_id=tenant.id,
                transaction_type=service,
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
                currency="ZAR",
                min_amount=Decimal("1"),
                max_amount=Decimal("100000"),
            )
        )
    await session.commit()


@pytest_asyncio.fixture
async def fund_withdraw_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Seed pricing + limit configs for both fund and withdraw so the gate passes.

    Requested by every transacting fund/withdraw test; the fail-closed gate
    (invariant #12) would otherwise reject them 422 before any ledger work.
    """
    await _seed_service_configs(db_session, test_tenant, service="fund")
    await _seed_service_configs(db_session, test_tenant, service="withdraw")


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
        # Reuse the tenant's pre-funded cash float (get-or-create) instead of a
        # second system_cash_inflow row (unique index) — its positive balance
        # absorbs the bootstrap DEBIT below (the float now has a no-overdraft floor).
        from app.modules.payments.service import get_or_create_system_cash_inflow

        inflow = await get_or_create_system_cash_inflow(session, tenant.id, "ZAR")
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
    fund_withdraw_configs: None,
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
    fund_withdraw_configs: None,
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
    fund_withdraw_configs: None,
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
    fund_withdraw_configs: None,
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
    fund_withdraw_configs: None,
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
    fund_withdraw_configs: None,
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
    # The gate needs a pricing config too; add it (zero-fee) so the request
    # reaches the limit check and trips AmountAboveMax rather than the gate.
    await _seed_service_configs(
        db_session, test_tenant, service="withdraw", with_limit=False
    )
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
    fund_withdraw_configs: None,
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


# -----------------------------------------------------------------------------
# Concurrency regressions (Epic 18 S4 — H-01 withdraw race, M-01 fund race)
#
# These exercise a REAL row-lock race: each concurrent request runs on its own
# session + asyncpg connection (async_client dep override + NullPool), so two
# in-flight money moves on the same wallet genuinely contend in Postgres.
# Mirrors the p2p (test_p2p_transfer.py) and redemption race tests.
# -----------------------------------------------------------------------------


async def _ledger_net_completed(session: AsyncSession) -> Decimal:
    """System-wide SUM(CREDIT) - SUM(DEBIT) over COMPLETED entries.

    The double-entry invariant (NFR-0100) requires this to be exactly zero;
    a double-spend that drives a balance negative still nets to zero at the
    ledger level, so this is a belt-and-braces check that the race never
    writes an *unbalanced* transaction, complementing the balance assertions.
    """
    result = await session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount),
                        else_=-LedgerEntry.amount,
                    )
                ),
                0,
            )
        ).where(LedgerEntry.status == ENTRY_STATUS_COMPLETED)
    )
    return Decimal(result.scalar_one() or 0)


async def _count_debits(session: AsyncSession, account_id) -> int:
    """Count COMPLETED DEBIT entries against an account (posted withdraws)."""
    result = await session.execute(
        select(func.count())
        .select_from(LedgerEntry)
        .where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.entry_type == ENTRY_DEBIT,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_external_withdraw_concurrent_distinct_keys_cannot_overdraft(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
    fund_withdraw_configs: None,
) -> None:
    """H-01: two concurrent withdraws (DISTINCT keys) for the full balance must
    NOT both commit — exactly one succeeds, the wallet never goes negative, and
    exactly one debit is posted.

    Distinct keys defeat the idempotency guard by design, so the ONLY thing that
    can prevent the double-spend is the wallet FOR UPDATE lock held continuously
    through the debit commit.
    """
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("100"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "amount": "100",  # each request pulls the FULL balance
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()

    def _withdraw(idem: str) -> asyncio.Task[object]:
        return asyncio.create_task(
            async_client.post(
                "/api/v1/external/withdraw",
                content=raw,
                headers=_sign(api_key["key_id"], api_key["secret"], raw, idem=idem),
            )
        )

    res_a, res_b = await asyncio.gather(_withdraw(uuid4().hex), _withdraw(uuid4().hex))

    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one success + one overdraft, got {statuses}"
    loser = res_a if res_a.status_code == 409 else res_b
    assert loser.json()["error_code"] == "insufficient_funds"

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0"), f"wallet drove negative/double-spent: {balance}"
    assert await _count_debits(db_session, wallet.id) == 1, "more than one debit posted"
    assert await _ledger_net_completed(db_session) == Decimal("0")


@pytest.mark.asyncio
async def test_external_withdraw_all_concurrent_cannot_double_drain(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
    fund_withdraw_configs: None,
) -> None:
    """H-01 (withdraw_all variant): two concurrent `withdraw_all` calls cannot
    each pull the full balance. withdraw_all needs no balance knowledge, so the
    race is easier to trigger — exactly one drains it, the other gets 409."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("100"))
    body = {
        "identifier_type": "phone",
        "identifier_value": _user_phone(test_user),
        "withdraw_all": True,
        "currency": "ZAR",
    }
    raw = json.dumps(body).encode()

    def _withdraw_all(idem: str) -> asyncio.Task[object]:
        return asyncio.create_task(
            async_client.post(
                "/api/v1/external/withdraw",
                content=raw,
                headers=_sign(api_key["key_id"], api_key["secret"], raw, idem=idem),
            )
        )

    res_a, res_b = await asyncio.gather(_withdraw_all(uuid4().hex), _withdraw_all(uuid4().hex))

    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one drain + one 409, got {statuses}"
    winner = res_a if res_a.status_code == 201 else res_b
    assert Decimal(winner.json()["amount"]) == Decimal("100")

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0"), f"wallet drove negative/double-drained: {balance}"
    assert await _count_debits(db_session, wallet.id) == 1, "more than one debit posted"
    assert await _ledger_net_completed(db_session) == Decimal("0")


@pytest.mark.asyncio
async def test_external_fund_concurrent_cannot_exceed_max_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
    fund_withdraw_configs: None,
) -> None:
    """M-01: with a max_balance ceiling configured, two concurrent funds that are
    each individually under the cap but jointly over it must NOT both land — the
    wallet may never exceed max_balance.

    Cap 150, wallet starts at 0, each fund is 100: sequentially the first lands
    (100) and the second is rejected (100+100 > 150). Without a wallet lock, both
    read balance 0 and both pass the check → balance 200, breaching the cap.
    """
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    # user_type IS NULL → applies to every user_type (incl. the consumer default).
    db_session.add(
        WalletLimitConfig(tenant_id=test_tenant.id, currency="ZAR", max_balance=Decimal("150"))
    )
    await db_session.commit()

    body = _fund_body(_user_phone(test_user), amount="100")
    raw = json.dumps(body).encode()

    def _fund(idem: str) -> asyncio.Task[object]:
        return asyncio.create_task(
            async_client.post(
                "/api/v1/external/fund",
                content=raw,
                headers=_sign(api_key["key_id"], api_key["secret"], raw, idem=idem),
            )
        )

    res_a, res_b = await asyncio.gather(_fund(uuid4().hex), _fund(uuid4().hex))

    statuses = sorted([res_a.status_code, res_b.status_code])
    assert statuses == [201, 409], f"expected one fund + one cap-breach, got {statuses}"
    loser = res_a if res_a.status_code == 409 else res_b
    assert loser.json()["error_code"] == "max_balance_exceeded"

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("100"), f"max_balance ceiling breached: {balance}"
    assert await _ledger_net_completed(db_session) == Decimal("0")


# -----------------------------------------------------------------------------
# Fail-closed service gate (invariant #12, Epic 23)
#
# Every money path must reject 422 `service_not_configured` when EITHER a
# pricing OR a limit config is missing for the target user's scope, before any
# ledger work. External fund/withdraw target the user's financial_wallet.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_fund_fails_closed_when_no_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """No fund pricing/limit config → 422 service_not_configured, no credit."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    # No ledger write happened.
    assert await derive_balance(db_session, wallet.id) == (Decimal("0"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_fund_fails_closed_when_only_pricing(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Pricing present but limit missing → still 422 (BOTH required)."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_service_configs(db_session, test_tenant, service="fund", with_limit=False)
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await derive_balance(db_session, wallet.id) == (Decimal("0"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_fund_succeeds_once_both_configs_exist(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """With BOTH a pricing and a limit config the fund goes through (201)."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("0"))
    await _seed_service_configs(db_session, test_tenant, service="fund")
    raw = json.dumps(_fund_body(_user_phone(test_user))).encode()
    resp = await async_client.post(
        "/api/v1/external/fund",
        content=raw,
        headers=_sign(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    assert await derive_balance(db_session, wallet.id) == (Decimal("100"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_withdraw_fails_closed_when_no_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """No withdraw pricing/limit config → 422 service_not_configured, no debit."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
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
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    # Balance untouched — the gate fired before any ledger work.
    assert await derive_balance(db_session, wallet.id) == (Decimal("500"), Decimal("0"))


@pytest.mark.asyncio
async def test_external_withdraw_fails_closed_when_only_limit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    api_key: dict[str, str],
) -> None:
    """Limit present but pricing missing → still 422 (BOTH required)."""
    wallet = await _seed_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    await _seed_service_configs(db_session, test_tenant, service="withdraw", with_pricing=False)
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
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_not_configured"
    assert await derive_balance(db_session, wallet.id) == (Decimal("500"), Decimal("0"))
