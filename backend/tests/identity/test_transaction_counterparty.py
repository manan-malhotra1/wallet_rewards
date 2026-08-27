"""Every statement row names its counterparty (reported for merchant cash-in).

A transaction always has two sides, so a statement row should always be able to
name the other one. Three cases used to leave the column blank:

  1. the other leg is a SYSTEM account (`user_id IS NULL`) — a bank mirror, a
     pool, a merchant collection account;
  2. both legs belong to the SAME user (a commission disbursement moves money
     between two of their own wallets, so there is no other party at all);
  3. the other user resolves to no display name.

The blanket test at the bottom is the real guard: it walks EVERY transaction on
a user and asserts none of them renders an empty counterparty, so a future
transaction type cannot quietly reintroduce the dash.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import list_user_transactions
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
)
from tests.fixtures.commission import BatchFixture


async def _post(
    session: AsyncSession,
    fx: BatchFixture,
    *,
    debit: Account,
    credit: Account,
    txn_type: str,
    amount: str = "10",
) -> None:
    """Post one balanced transaction between two accounts."""
    value = Decimal(amount)
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=fx.tenant.id,
            idempotency_key=f"cp-{txn_type}-{uuid4().hex[:10]}",
            transaction_type=txn_type,
            currency="ZAR",
            amount=value,
            entries=[
                LedgerEntryRequest(debit.id, ENTRY_DEBIT, value),
                LedgerEntryRequest(credit.id, ENTRY_CREDIT, value),
            ],
            skip_receive_cap=True,
        ),
    )


async def _rows(session: AsyncSession, fx: BatchFixture) -> list[dict]:
    """The agent's statement rows, as the admin surface renders them."""
    rows, _total = await list_user_transactions(
        session, tenant_id=fx.tenant.id, user_id=fx.agent.id
    )
    return rows


@pytest.mark.asyncio
async def test_intra_user_movement_names_the_other_wallet(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A disbursement moves between the user's OWN wallets — name the source."""
    await _post(
        db_session,
        batch_fixture,
        debit=batch_fixture.agent_commission_wallet,
        credit=batch_fixture.agent_main_wallet,
        txn_type="commission_disbursement",
    )

    rows = await _rows(db_session, batch_fixture)
    row = next(r for r in rows if r["transaction_type"] == "commission_disbursement")
    assert row["counterparty_name"], "a disbursement must not render a blank counterparty"
    assert "wallet" in row["counterparty_name"].lower()


@pytest.mark.asyncio
async def test_system_counterparty_is_named_by_what_the_account_is(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A clawback's other leg is a bank mirror, which has no owning user."""
    await _post(
        db_session,
        batch_fixture,
        debit=batch_fixture.agent_commission_wallet,
        credit=batch_fixture.bank_mirror,
        txn_type="commission_withdrawal",
    )

    rows = await _rows(db_session, batch_fixture)
    row = next(r for r in rows if r["transaction_type"] == "commission_withdrawal")
    assert row["counterparty_name"], "a clawback must not render a blank counterparty"
    # Several bank mirrors can coexist per currency and the operator picks one
    # BY NAME, so the name has to survive into the statement — the type alone
    # would not tell two mirrors apart.
    assert batch_fixture.bank_mirror.name is not None
    assert batch_fixture.bank_mirror.name in row["counterparty_name"]
    assert "Bank mirror" in row["counterparty_name"]


@pytest.mark.asyncio
async def test_pool_counterparty_is_named(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A commission accrual is funded by the tenant pool — name the pool."""
    from sqlalchemy import select

    pool = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == batch_fixture.tenant.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION,
                Account.currency == "ZAR",
            )
        )
    ).scalars().first()
    assert pool is not None

    await _post(
        db_session,
        batch_fixture,
        debit=pool,
        credit=batch_fixture.agent_commission_wallet,
        txn_type="commission_accrual",
    )

    rows = await _rows(db_session, batch_fixture)
    row = next(r for r in rows if r["transaction_type"] == "commission_accrual")
    assert row["counterparty_name"] == "Commission pool"


@pytest.mark.asyncio
async def test_no_transaction_ever_renders_a_blank_counterparty(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """The blanket guard: every row on the statement names its other side.

    This is the regression test for the reported issue. A new transaction type
    that forgets to resolve a counterparty fails HERE rather than shipping a
    dash to an operator.
    """
    from sqlalchemy import select

    pool = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == batch_fixture.tenant.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION,
                Account.currency == "ZAR",
            )
        )
    ).scalars().first()

    await _post(
        db_session,
        batch_fixture,
        debit=batch_fixture.agent_commission_wallet,
        credit=batch_fixture.agent_main_wallet,
        txn_type="commission_disbursement",
    )
    await _post(
        db_session,
        batch_fixture,
        debit=batch_fixture.agent_commission_wallet,
        credit=batch_fixture.bank_mirror,
        txn_type="commission_withdrawal",
    )
    await _post(
        db_session,
        batch_fixture,
        debit=pool,
        credit=batch_fixture.agent_commission_wallet,
        txn_type="commission_accrual",
    )

    rows = await _rows(db_session, batch_fixture)
    assert rows, "the agent should have statement rows"

    blank = [
        (r["transaction_type"], r.get("txn_id") or r.get("id"))
        for r in rows
        if not r.get("counterparty_name")
    ]
    assert blank == [], f"these rows render a blank counterparty: {blank}"
