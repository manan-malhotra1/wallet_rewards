"""Wallet balance limits.

The guard locks every user `financial_wallet` leg and enforces overdraft (net
debit) + max_balance (net credit) UNDER that lock — the single authoritative
place these limits hold, so every money path inherits them by posting here. The
concurrency proofs live with the endpoints (p2p receive cap, external
fund/withdraw races); these cover the guard's account classification and the
reversal exemption directly against the ledger service.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.shared.exceptions import InsufficientFunds, MaxBalanceExceeded
from app.shared.models import (
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    User,
    WalletLimitConfig,
)


async def _zar_inflow(session: AsyncSession, tenant: Tenant) -> Account:
    """The ZAR system_cash_inflow counter account.

    Uses get-or-create so it lands on the `test_tenant` fixture's pre-funded
    float row rather than colliding with it (the float now carries a
    no-overdraft floor and is pre-funded in the fixture). Its large positive
    balance means the DEBIT legs below are absorbed by the float, so these tests
    still exercise the user-wallet cap / overdraft, not the float floor.
    """
    from app.modules.payments.service import get_or_create_system_cash_inflow

    return await get_or_create_system_cash_inflow(session, tenant.id, "ZAR")


async def _set_zar_cap(session: AsyncSession, tenant: Tenant, cap: str) -> None:
    """Configure a tenant-wide ZAR max_balance ceiling (user_type NULL = all)."""
    session.add(WalletLimitConfig(tenant_id=tenant.id, currency="ZAR", max_balance=Decimal(cap)))
    await session.commit()


@pytest.mark.asyncio
async def test_guard_rejects_credit_over_max_balance(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a customer cannot hold more than their wallet's maximum balance"""
    inflow = await _zar_inflow(db_session, test_tenant)
    await _set_zar_cap(db_session, test_tenant, "100")

    with pytest.raises(MaxBalanceExceeded):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="cap-reject-1",
                transaction_type="fund",
                currency="ZAR",
                initiated_by=test_user.id,
                entries=[
                    LedgerEntryRequest(
                        account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=Decimal("150")
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id, entry_type=ENTRY_CREDIT, amount=Decimal("150")
                    ),
                ],
            ),
        )
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("0")


@pytest.mark.asyncio
async def test_guard_allows_reversal_over_max_balance(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a refund can be received even when it pushes a wallet past its maximum balance

    A reversal / refund is cap-exempt (invariant #11b): restoring funds may push
    a wallet over max_balance and must never be blocked."""
    inflow = await _zar_inflow(db_session, test_tenant)
    await _set_zar_cap(db_session, test_tenant, "100")

    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="reversal-1",
            transaction_type="reversal",
            currency="ZAR",
            initiated_by=test_user.id,
            is_reversal=True,
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=Decimal("150")
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id, entry_type=ENTRY_CREDIT, amount=Decimal("150")
                ),
            ],
        ),
    )
    assert txn.status == "COMPLETED"
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("150")  # landed despite the 100 cap


@pytest.mark.asyncio
async def test_guard_skips_collection_account_credit(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a merchant collection account has no balance ceiling

    A credit to a merchant collection account is never cap-checked, even with a
    currency cap configured — pool accounts have no ceiling (invariant #11a)."""
    inflow = await _zar_inflow(db_session, test_tenant)
    await _set_zar_cap(db_session, test_tenant, "100")
    holding = Account(
        tenant_id=test_tenant.id,
        account_type=ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
        currency="ZAR",
    )
    db_session.add(holding)
    await db_session.commit()
    await db_session.refresh(holding)

    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="pool-credit-1",
            transaction_type="airtime_recharge",
            currency="ZAR",
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=Decimal("500")
                ),
                LedgerEntryRequest(
                    account_id=holding.id, entry_type=ENTRY_CREDIT, amount=Decimal("500")
                ),
            ],
        ),
    )
    assert txn.status == "COMPLETED"
    balance, _ = await derive_balance(db_session, holding.id)
    assert balance == Decimal("500")  # 500 > 100 cap, but pool accounts are exempt


@pytest.mark.asyncio
async def test_guard_rejects_debit_over_available_balance(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a customer cannot spend more than their wallet balance"""
    inflow = await _zar_inflow(db_session, test_tenant)
    # user_wallet opens at 0 — debiting 50 must fail overdraft.
    with pytest.raises(InsufficientFunds):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="overdraft-1",
                transaction_type="withdraw",
                currency="ZAR",
                initiated_by=test_user.id,
                entries=[
                    LedgerEntryRequest(
                        account_id=user_wallet.id, entry_type=ENTRY_DEBIT, amount=Decimal("50")
                    ),
                    LedgerEntryRequest(
                        account_id=inflow.id, entry_type=ENTRY_CREDIT, amount=Decimal("50")
                    ),
                ],
            ),
        )
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("0")
