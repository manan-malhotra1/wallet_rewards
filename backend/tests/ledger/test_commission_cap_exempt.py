"""Agent commission payouts.

A commission CREDIT to an agent at max_balance is an earned payout and must
land; `skip_receive_cap` exempts credit legs from the ceiling (like a reversal)
WITHOUT marking the transaction a reversal. Overdraft on debit legs still holds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.pricing.service import get_or_create_system_commission
from app.shared.exceptions import MaxBalanceExceeded
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    User,
    WalletLimitConfig,
)


async def _set_zar_cap(session: AsyncSession, tenant: Tenant, cap: str) -> None:
    session.add(WalletLimitConfig(tenant_id=tenant.id, currency="ZAR", max_balance=Decimal(cap)))
    await session.commit()


@pytest.mark.asyncio
async def test_commission_credit_lands_at_max_balance(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
) -> None:
    """Verify an agent receives earned commission even at their wallet's maximum balance"""
    await _set_zar_cap(db_session, test_tenant, "100")
    pool = await get_or_create_system_commission(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    await db_session.commit()

    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="commission-payout-1",
            transaction_type="cash_in",
            currency="ZAR",
            skip_receive_cap=True,
            commission_amount=Decimal("150"),
            entries=[
                LedgerEntryRequest(
                    account_id=pool.id, entry_type=ENTRY_DEBIT, amount=Decimal("150")
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id, entry_type=ENTRY_CREDIT, amount=Decimal("150")
                ),
            ],
        ),
    )
    assert txn.status == "COMPLETED"
    assert txn.commission_amount == Decimal("150.000000")
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("150")  # landed despite the 100 cap


@pytest.mark.asyncio
async def test_normal_credit_over_cap_still_rejected(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
) -> None:
    """Verify an ordinary top-up over the wallet maximum is still refused"""
    await _set_zar_cap(db_session, test_tenant, "100")
    pool = await get_or_create_system_commission(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    await db_session.commit()

    with pytest.raises(MaxBalanceExceeded):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="normal-credit-1",
                transaction_type="fund",
                currency="ZAR",
                initiated_by=test_user.id,
                entries=[
                    LedgerEntryRequest(
                        account_id=pool.id, entry_type=ENTRY_DEBIT, amount=Decimal("150")
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id, entry_type=ENTRY_CREDIT, amount=Decimal("150")
                    ),
                ],
            ),
        )
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("0")
