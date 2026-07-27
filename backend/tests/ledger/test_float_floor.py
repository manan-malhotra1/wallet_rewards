"""Operator float safeguards.

The cash float is a POSITIVE balance topped up from the bank; float-sourced
funding (admin `fund` / external partner fund — both DEBIT the float) may run
only while the float can absorb the debit. `post_transaction`'s balance guard
(invariant #11) locks the float FOR UPDATE and rejects any net debit that would
drive it below zero with a distinct `InsufficientFloat` (409), BEFORE any ledger
write. Crediting the float (a bank top-up or a fund reversal) is never blocked.

These tests use FRESH, un-prefunded tenants (NOT the `test_tenant` fixture,
whose ZAR float is pre-funded) so the floor is actually exercised.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import ApiKeyPrincipal
from app.auth.principals import AdminPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.external.schemas import ExternalFundRequest
from app.modules.external.service import external_fund
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.payments.service import fund, get_or_create_system_cash_inflow
from app.modules.treasury.service import adjust_system_wallet
from app.shared.exceptions import (
    FundingTemporarilyUnavailable,
    InsufficientFloat,
    InsufficientFunds,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    LimitConfig,
    PricingConfig,
    Tenant,
    Transaction,
    User,
    UserIdentifier,
)
from tests.conftest import TestSessionLocal

_ADMIN = AdminPrincipal(
    id="00000000-0000-4000-8000-0000000000ad", username="admin", roles=frozenset()
)


async def _fresh_tenant(session: AsyncSession) -> Tenant:
    """A brand-new tenant whose ZAR float is NOT pre-funded (float starts at 0)."""
    tenant = Tenant(
        name=f"float-floor-{uuid4().hex[:8]}", business_type="both", base_currency="ZAR"
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    return tenant


async def _user_with_wallet(session: AsyncSession, tenant: Tenant) -> tuple[User, Account]:
    """A user with one phone identifier and one (empty) ZAR financial_wallet."""
    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=f"+27 82 555 {uuid4().int % 10000:04d}",
            verified=True,
        )
    )
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(user, attribute_names=["identifiers"])
    await session.refresh(wallet)
    return user, wallet


async def _seed_fund_configs(session: AsyncSession, tenant: Tenant) -> None:
    """Seed zero-fee pricing + wide limit for `fund` so the invariant-#12 gate passes."""
    session.add(
        PricingConfig(
            tenant_id=tenant.id,
            transaction_type="fund",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
        )
    )
    session.add(
        LimitConfig(
            tenant_id=tenant.id,
            transaction_type="fund",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            min_amount=Decimal("1"),
            max_amount=Decimal("100000"),
        )
    )
    await session.commit()


async def _top_up_float_via_bank(session: AsyncSession, tenant: Tenant, amount: Decimal) -> None:
    """Inject float from the bank mirror via the real `adjust_system_wallet` path."""
    inflow = await get_or_create_system_cash_inflow(session, tenant.id, "ZAR")
    mirror = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency="ZAR",
        name="Primary",
    )
    session.add(mirror)
    await session.commit()
    await session.refresh(inflow)
    await session.refresh(mirror)
    await adjust_system_wallet(
        session,
        tenant_id=tenant.id,
        account_id=inflow.id,
        amount=amount,  # positive => fund the float
        bank_mirror_account_id=mirror.id,
        reason="test top-up",
        admin=_ADMIN,
    )


async def _count_txns(session: AsyncSession, tenant: Tenant) -> int:
    result = await session.execute(
        select(func.count()).select_from(Transaction).where(Transaction.tenant_id == tenant.id)
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_fund_rejected_when_float_empty(db_session: AsyncSession) -> None:
    """Verify a payout is blocked when the operator float has run out"""
    tenant = await _fresh_tenant(db_session)
    user, wallet = await _user_with_wallet(db_session, tenant)
    txns_before = await _count_txns(db_session, tenant)

    with pytest.raises(InsufficientFloat):
        await fund(
            db_session,
            tenant_id=tenant.id,
            user_id=user.id,
            amount=Decimal("100"),
            currency="ZAR",
            idempotency_key="fund-empty-float",
        )

    # No ledger entries written, wallet unchanged, no new transaction row.
    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0")
    assert await _count_txns(db_session, tenant) == txns_before


@pytest.mark.asyncio
async def test_fund_succeeds_after_float_topped_up(db_session: AsyncSession) -> None:
    """Verify a payout succeeds once the operator float has been topped up from the bank"""
    tenant = await _fresh_tenant(db_session)
    user, wallet = await _user_with_wallet(db_session, tenant)
    await _top_up_float_via_bank(db_session, tenant, Decimal("500"))

    txn = await fund(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="fund-after-topup",
    )
    assert txn.status == "COMPLETED"

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("100")
    # Float drew down from 500 to 400.
    inflow = await get_or_create_system_cash_inflow(db_session, tenant.id, "ZAR")
    float_balance, _ = await derive_balance(db_session, inflow.id)
    assert float_balance == Decimal("400")


@pytest.mark.asyncio
async def test_external_partner_fund_floored_on_empty_float(db_session: AsyncSession) -> None:
    """Verify a partner top-up is turned away without revealing that the operator float is empty

    The external partner fund path is ALSO floored — it DEBITs the same float.

    But the partner MUST NOT see the operator-facing `insufficient_float` message
    (it leaks operator liquidity state, security review): the float error is
    masked to a generic 503 `funding_temporarily_unavailable` on this surface.
    """
    tenant = await _fresh_tenant(db_session)
    user, wallet = await _user_with_wallet(db_session, tenant)
    await _seed_fund_configs(db_session, tenant)  # so the gate passes; the floor is what trips
    principal = ApiKeyPrincipal(tenant_id=tenant.id, key_id="k-floor")
    phone = next(i.identifier_value for i in user.identifiers if i.identifier_type == "phone")

    with pytest.raises(FundingTemporarilyUnavailable) as exc_info:
        await external_fund(
            db_session,
            principal=principal,
            request=ExternalFundRequest(
                identifier_type="phone",
                identifier_value=phone,
                amount=Decimal("100"),
                currency="ZAR",
                reason="partner top-up",
            ),
            idempotency_key="ext-fund-empty-float",
        )

    # Generic 503, and the operator-facing float message is NOT leaked.
    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "funding_temporarily_unavailable"
    assert "float" not in exc_info.value.message.lower()

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0")


@pytest.mark.asyncio
async def test_fund_reversal_credits_float_and_is_not_blocked(db_session: AsyncSession) -> None:
    """Verify reversing a payout returns the money to the operator float

    A fund REVERSAL credits the float back — a net credit to the float is never
    blocked by the floor (crediting the float can only raise it)."""
    tenant = await _fresh_tenant(db_session)
    user, wallet = await _user_with_wallet(db_session, tenant)
    await _top_up_float_via_bank(db_session, tenant, Decimal("500"))
    inflow = await get_or_create_system_cash_inflow(db_session, tenant.id, "ZAR")

    # Fund 100: float 500 -> 400, wallet 0 -> 100.
    await fund(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="fund-to-reverse",
    )

    # Reverse it: DEBIT wallet / CREDIT float (is_reversal — cap-exempt anyway).
    reversal = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key="fund-reversal",
            transaction_type="fund_reversal",
            currency="ZAR",
            amount=Decimal("100"),
            is_reversal=True,
            entries=[
                LedgerEntryRequest(
                    account_id=wallet.id, entry_type=ENTRY_DEBIT, amount=Decimal("100")
                ),
                LedgerEntryRequest(
                    account_id=inflow.id, entry_type=ENTRY_CREDIT, amount=Decimal("100")
                ),
            ],
        ),
    )
    assert reversal.status == "COMPLETED"
    float_balance, _ = await derive_balance(db_session, inflow.id)
    assert float_balance == Decimal("500")  # restored
    wallet_balance, _ = await derive_balance(db_session, wallet.id)
    assert wallet_balance == Decimal("0")


@pytest.mark.asyncio
async def test_financial_wallet_overdraft_still_insufficient_funds(
    db_session: AsyncSession,
) -> None:
    """Verify a customer overdraft is reported as insufficient funds, not as an empty float

    A user-wallet overdraft still raises the ordinary InsufficientFunds — the
    new InsufficientFloat is reserved for the cash float only."""
    tenant = await _fresh_tenant(db_session)
    _user, wallet = await _user_with_wallet(db_session, tenant)
    inflow = await get_or_create_system_cash_inflow(db_session, tenant.id, "ZAR")

    with pytest.raises(InsufficientFunds):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=tenant.id,
                idempotency_key="wallet-overdraft",
                transaction_type="withdraw",
                currency="ZAR",
                amount=Decimal("50"),
                entries=[
                    LedgerEntryRequest(
                        account_id=wallet.id, entry_type=ENTRY_DEBIT, amount=Decimal("50")
                    ),
                    LedgerEntryRequest(
                        account_id=inflow.id, entry_type=ENTRY_CREDIT, amount=Decimal("50")
                    ),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_concurrent_funds_cannot_overdraw_float(db_session: AsyncSession) -> None:
    """Verify two payouts at once can never drain the operator float below zero

    M-01 (float axis): two concurrent funds that TOGETHER exceed the float — the
    FOR UPDATE lock on the single float row serialises them, exactly one succeeds,
    and the float never goes negative.

    Setup runs on `db_session`; the two racing funds each use their OWN session
    (asyncpg allows one op per connection), mirroring two real concurrent requests.
    """
    tenant = await _fresh_tenant(db_session)
    user_a, wallet_a = await _user_with_wallet(db_session, tenant)
    user_b, wallet_b = await _user_with_wallet(db_session, tenant)
    # Float = 100; each fund wants 60 → jointly 120 > 100. Pre-create the float row
    # (topped up) so neither concurrent fund creates+commits it mid-flight.
    await _top_up_float_via_bank(db_session, tenant, Decimal("100"))
    inflow = await get_or_create_system_cash_inflow(db_session, tenant.id, "ZAR")

    async def _fund_in_new_session(user_id: object, key: str) -> object:
        async with TestSessionLocal() as session:
            try:
                await fund(
                    session,
                    tenant_id=tenant.id,
                    user_id=user_id,
                    amount=Decimal("60"),
                    currency="ZAR",
                    idempotency_key=key,
                )
                return "ok"
            except InsufficientFloat:
                return "insufficient_float"

    results = await asyncio.gather(
        _fund_in_new_session(user_a.id, "race-a"),
        _fund_in_new_session(user_b.id, "race-b"),
    )
    assert sorted(results) == ["insufficient_float", "ok"], results

    # The float never went negative: one 60 debit landed, 100 - 60 = 40.
    float_balance, _ = await derive_balance(db_session, inflow.id)
    assert float_balance == Decimal("40")
    assert float_balance >= Decimal("0")
    # Exactly one wallet was funded.
    bal_a, _ = await derive_balance(db_session, wallet_a.id)
    bal_b, _ = await derive_balance(db_session, wallet_b.id)
    assert sorted([bal_a, bal_b]) == [Decimal("0"), Decimal("60")]
