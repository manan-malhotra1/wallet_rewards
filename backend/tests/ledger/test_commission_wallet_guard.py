"""Commission wallet guard shape — floored, uncapped, cap-exempt (spec §5, D5).

Three properties, each of which would be silently wrong under a naive "just add
it to the guarded set" change:

  1. A credit far above the owner's max_balance SUCCEEDS (no ceiling). This is
     the one a naive change breaks: the ceiling branch used to key off
     `account.user_id is not None`, and a commission wallet HAS an owner.
  2. A debit that would overdraw it is REJECTED with the distinct 409.
  3. A debit it can cover succeeds and lands the balance exactly on zero.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import InsufficientCommissionBalance
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    User,
)


async def _make_account(
    session: AsyncSession, tenant: Tenant, account_type: str, user: User | None
) -> Account:
    """Persist one account of a type, owned by `user` or system-owned."""
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id if user is not None else None,
        account_type=account_type,
        currency="ZAR",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _accrue(
    session: AsyncSession,
    tenant: Tenant,
    pool: Account,
    wallet: Account,
    amount: Decimal,
    key: str,
) -> None:
    """Post pool -> commission wallet, the shape a real commission credit uses."""
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=key,
            transaction_type="commission_accrual",
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, amount),
                LedgerEntryRequest(wallet.id, ENTRY_CREDIT, amount),
            ],
        ),
    )


@pytest.mark.asyncio
async def test_credit_above_max_balance_succeeds(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """No ceiling: an agent may accrue any amount of commission (D5).

    Deliberately NOT flagged `skip_receive_cap` — the exemption must come from
    the account TYPE, not from the caller remembering to pass a flag.
    """
    pool = await _make_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _make_account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )

    await _accrue(db_session, test_tenant, pool, wallet, Decimal("99999999"), "acc-1")

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("99999999")


@pytest.mark.asyncio
async def test_debit_below_zero_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Floored: a disbursement may never overdraw a commission wallet (D5)."""
    pool = await _make_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _make_account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _accrue(db_session, test_tenant, pool, wallet, Decimal("100"), "acc-2")

    with pytest.raises(InsufficientCommissionBalance):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="disb-over",
                transaction_type="commission_disbursement",
                currency="ZAR",
                amount=Decimal("150"),
                entries=[
                    LedgerEntryRequest(wallet.id, ENTRY_DEBIT, Decimal("150")),
                    LedgerEntryRequest(pool.id, ENTRY_CREDIT, Decimal("150")),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_debit_within_balance_succeeds(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Draining the wallet exactly to zero is allowed — the floor is >= 0."""
    pool = await _make_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _make_account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _accrue(db_session, test_tenant, pool, wallet, Decimal("100"), "acc-3")

    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="disb-ok",
            transaction_type="commission_disbursement",
            currency="ZAR",
            amount=Decimal("100"),
            entries=[
                LedgerEntryRequest(wallet.id, ENTRY_DEBIT, Decimal("100")),
                LedgerEntryRequest(pool.id, ENTRY_CREDIT, Decimal("100")),
            ],
        ),
    )

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0")
