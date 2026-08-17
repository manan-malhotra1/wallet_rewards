"""base_transaction_type plumbing through the ledger choke point.

Every transaction records the BASE flow it belongs to so clients can group by
flow without knowing every derived code (spec §12.1). Callers that don't pass
one get their transaction_type, which keeps all pre-existing flows correct.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import ENTRY_CREDIT, ENTRY_DEBIT, Account, Tenant


def _balanced_p2p(
    src: Account, dst: Account, amount: Decimal, currency: str = "ZAR"
) -> list[LedgerEntryRequest]:
    """Helper: build a balanced 2-entry pair (debit src, credit dst)."""
    return [
        LedgerEntryRequest(account_id=src.id, entry_type=ENTRY_DEBIT, amount=amount),
        LedgerEntryRequest(account_id=dst.id, entry_type=ENTRY_CREDIT, amount=amount),
    ]


@pytest.mark.asyncio
async def test_base_transaction_type_defaults_to_transaction_type(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify a caller that omits the base gets transaction_type recorded"""
    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="base-default-1",
            transaction_type="p2p",
            currency="ZAR",
            entries=_balanced_p2p(system_points_account, user_wallet, Decimal("25")),
        ),
    )
    assert txn.transaction_type == "p2p"
    assert txn.base_transaction_type == "p2p"


@pytest.mark.asyncio
async def test_base_transaction_type_is_recorded_when_supplied(
    db_session: AsyncSession,
    test_tenant: Tenant,
    system_points_account: Account,
    user_wallet: Account,
) -> None:
    """Verify an explicit base is stored alongside a derived transaction_type"""
    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="base-explicit-1",
            transaction_type="p2p_diaspora",
            base_transaction_type="p2p",
            currency="ZAR",
            entries=_balanced_p2p(system_points_account, user_wallet, Decimal("25")),
        ),
    )
    assert txn.transaction_type == "p2p_diaspora"
    assert txn.base_transaction_type == "p2p"
