"""Commission and tax holding accounts.

Covers the two lazy get-or-create helpers (create-once + idempotent refetch)
and confirms the balance guard skips both types: a large credit/debit to a
`commission` or `taxes` account never trips overdraft or `max_balance`, because
these are unguarded pool accounts (invariant #11a).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.pricing.service import (
    get_or_create_system_commission,
    get_or_create_system_tax_service,
)
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_TAX_SERVICE,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Tenant,
    WalletLimitConfig,
)


@pytest.mark.asyncio
async def test_get_or_create_commission_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify collected commission is gathered into one holding account."""
    first = await get_or_create_system_commission(
        db_session, tenant_id=test_tenant.id, currency="zar"
    )
    await db_session.commit()
    assert first.account_type == ACCOUNT_TYPE_COMMISSION
    assert first.currency == "ZAR"  # uppercased
    assert first.user_id is None

    second = await get_or_create_system_commission(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    assert second.id == first.id


@pytest.mark.asyncio
async def test_get_or_create_taxes_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify collected tax is gathered into one holding account."""
    first = await get_or_create_system_tax_service(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    await db_session.commit()
    assert first.account_type == ACCOUNT_TYPE_TAX_SERVICE

    second = await get_or_create_system_tax_service(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    assert second.id == first.id


@pytest.mark.asyncio
async def test_guard_skips_commission_and_taxes_credits(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify commission and tax holding accounts are not subject to customer balance limits.

    Even with a tenant-wide ZAR ceiling configured, a credit far above it lands
    on these unguarded pool accounts.
    """
    session = db_session
    session.add(
        WalletLimitConfig(tenant_id=test_tenant.id, currency="ZAR", max_balance=Decimal("100"))
    )
    commission = await get_or_create_system_commission(
        session, tenant_id=test_tenant.id, currency="ZAR"
    )
    taxes = await get_or_create_system_tax_service(
        session, tenant_id=test_tenant.id, currency="ZAR"
    )
    await session.commit()

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="commission-taxes-credit-1",
            transaction_type="cash_in",
            currency="ZAR",
            entries=[
                # commission pool goes "negative" (DEBIT) — no overdraft guard.
                LedgerEntryRequest(
                    account_id=commission.id, entry_type=ENTRY_DEBIT, amount=Decimal("5000")
                ),
                LedgerEntryRequest(
                    account_id=taxes.id, entry_type=ENTRY_CREDIT, amount=Decimal("5000")
                ),
            ],
        ),
    )
    assert txn.status == "COMPLETED"

    commission_balance, _ = await derive_balance(session, commission.id)
    taxes_balance, _ = await derive_balance(session, taxes.id)
    assert commission_balance == Decimal("-5000")  # ran negative, unguarded
    assert taxes_balance == Decimal("5000")  # far over the 100 cap, exempt
