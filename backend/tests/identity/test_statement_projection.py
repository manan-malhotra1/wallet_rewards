"""A statement row reports the CALLER'S movement, on ONE named wallet.

Regression cover for four reported defects, all on the same surface:

  * B14.1 — the row emitted `transactions.amount`, so a supervisor credited
    R0.50 of parent commission on a R100 cash-in was shown "+ZAR 100.00 IN".
  * B13.1 — no row said WHICH wallet moved, so with two wallets per currency
    held commission was indistinguishable from spendable money.
  * B13.2 — `direction` was read off whichever leg the ledger query returned
    first, which stopped being deterministic once a user could own two legs.
  * B13.3 — an agent's earned commission never appeared at all.

The projection now emits one row per (transaction, caller wallet), which makes
the amount, the direction and the wallet each unambiguous.
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
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
)

from tests.fixtures.commission import BatchFixture

# A headline deliberately orders of magnitude larger than the commission, so a
# regression that reverts `amount` to the transaction total cannot pass.
HEADLINE = Decimal("100")
COMMISSION = Decimal("0.50")


async def _pool(session: AsyncSession, fx: BatchFixture) -> Account:
    """The tenant commission pool that funds a payout."""
    from sqlalchemy import select

    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == fx.tenant.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION,
                Account.currency == "ZAR",
            )
        )
    ).scalars().first()


async def _rows(session: AsyncSession, fx: BatchFixture) -> list[dict]:
    """The agent's statement rows."""
    rows, _total = await list_user_transactions(
        session, tenant_id=fx.tenant.id, user_id=fx.agent.id
    )
    return rows


async def _supervisor_style_commission(
    session: AsyncSession, fx: BatchFixture
) -> None:
    """A transaction whose HEADLINE is large but whose only leg of the
    caller's is a small commission credit — the supervisor's case."""
    pool = await _pool(session, fx)
    customer_wallet = fx.agent_main_wallet  # stands in as the other side
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=fx.tenant.id,
            idempotency_key=f"sup-{uuid4().hex[:10]}",
            transaction_type="cash_in",
            currency="ZAR",
            # The HEADLINE the row used to report.
            amount=HEADLINE,
            entries=[
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, COMMISSION),
                LedgerEntryRequest(
                    fx.agent_commission_wallet.id, ENTRY_CREDIT, COMMISSION
                ),
            ],
            skip_receive_cap=True,
        ),
    )
    assert customer_wallet is not None


@pytest.mark.asyncio
async def test_amount_is_the_callers_movement_not_the_headline(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """B14.1 — the defect that overstated a supervisor's receipt 200x."""
    await _supervisor_style_commission(db_session, batch_fixture)

    row = next(r for r in await _rows(db_session, batch_fixture) if r["direction"] == "in")
    assert Decimal(row["amount"]) == COMMISSION
    assert Decimal(row["amount"]) != HEADLINE
    # The headline is still available, but as its own clearly-named field so it
    # can never be mistaken for the caller's movement again.
    assert Decimal(row["transaction_amount"]) == HEADLINE


@pytest.mark.asyncio
async def test_each_row_names_the_wallet_that_moved(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """B13.1 — held commission must be distinguishable from spendable money."""
    await _supervisor_style_commission(db_session, batch_fixture)

    row = next(r for r in await _rows(db_session, batch_fixture) if r["direction"] == "in")
    assert row["wallet_account_type"] == ACCOUNT_TYPE_COMMISSION_WALLET
    assert row["wallet_label"] == "Commission wallet"
    assert row["wallet_account_id"] == batch_fixture.agent_commission_wallet.id


@pytest.mark.asyncio
async def test_a_transaction_touching_two_wallets_yields_a_row_for_each(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """B13.3 — an agent's cash-in pays FROM one wallet and earns INTO another.

    Reporting only the payment made it read as though they worked for nothing.
    """
    pool = await _pool(db_session, batch_fixture)
    principal = Decimal("80")
    earned = Decimal("4")

    # The agent pays the principal out of their MAIN wallet, so it needs a
    # balance first — the fixture only pre-accrues commission.
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=batch_fixture.tenant.id,
            idempotency_key=f"prefund-{uuid4().hex[:10]}",
            transaction_type="fund",
            currency="ZAR",
            amount=principal,
            entries=[
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, principal),
                LedgerEntryRequest(
                    batch_fixture.agent_main_wallet.id, ENTRY_CREDIT, principal
                ),
            ],
            skip_receive_cap=True,
        ),
    )

    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=batch_fixture.tenant.id,
            idempotency_key=f"twoleg-{uuid4().hex[:10]}",
            transaction_type="cash_in",
            currency="ZAR",
            amount=principal,
            initiated_by=batch_fixture.agent.id,
            commission_amount=earned,
            entries=[
                LedgerEntryRequest(
                    batch_fixture.agent_main_wallet.id, ENTRY_DEBIT, principal
                ),
                LedgerEntryRequest(pool.id, ENTRY_CREDIT, principal),
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, earned),
                LedgerEntryRequest(
                    batch_fixture.agent_commission_wallet.id, ENTRY_CREDIT, earned
                ),
            ],
            skip_receive_cap=True,
        ),
    )

    rows = [r for r in await _rows(db_session, batch_fixture) if r["transaction_type"] == "cash_in"]
    by_wallet = {r["wallet_account_type"]: r for r in rows}

    paid = by_wallet[ACCOUNT_TYPE_FINANCIAL_WALLET]
    assert paid["direction"] == "out"
    assert Decimal(paid["amount"]) == principal

    earning = by_wallet[ACCOUNT_TYPE_COMMISSION_WALLET]
    assert earning["direction"] == "in"
    assert Decimal(earning["amount"]) == earned
    # The commission column rides the leg that received it, so it is reported
    # without consulting a per-transaction-type map.
    assert Decimal(earning["commission_amount"]) == earned
    # ...and is not double-counted against the wallet that merely paid.
    assert Decimal(paid["commission_amount"]) == 0


@pytest.mark.asyncio
async def test_direction_is_stable_when_the_caller_owns_both_legs(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """B13.2 — a disbursement moves between two of the caller's OWN wallets.

    Direction used to be decided by ledger entry ordering, so the same row
    could render IN on one load and OUT on the next.
    """
    amount = Decimal("25")
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=batch_fixture.tenant.id,
            idempotency_key=f"disb-{uuid4().hex[:10]}",
            transaction_type="commission_disbursement",
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(
                    batch_fixture.agent_commission_wallet.id, ENTRY_DEBIT, amount
                ),
                LedgerEntryRequest(
                    batch_fixture.agent_main_wallet.id, ENTRY_CREDIT, amount
                ),
            ],
            skip_receive_cap=True,
        ),
    )

    def disbursement_rows(rows: list[dict]) -> dict[str, str]:
        return {
            r["wallet_account_type"]: r["direction"]
            for r in rows
            if r["transaction_type"] == "commission_disbursement"
        }

    first = disbursement_rows(await _rows(db_session, batch_fixture))
    second = disbursement_rows(await _rows(db_session, batch_fixture))

    # Both wallets are reported, each with the direction ITS leg had, and the
    # answer does not change between loads.
    assert first == second
    assert first[ACCOUNT_TYPE_COMMISSION_WALLET] == "out"
    assert first[ACCOUNT_TYPE_FINANCIAL_WALLET] == "in"


@pytest.mark.asyncio
async def test_single_leg_transactions_are_unchanged(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """The parties that existed before commission wallets must not shift.

    For them the caller's own leg IS the headline, which is exactly why the old
    shortcut went unnoticed for so long.
    """
    pool = await _pool(db_session, batch_fixture)
    amount = Decimal("60")

    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=batch_fixture.tenant.id,
            idempotency_key=f"single-{uuid4().hex[:10]}",
            transaction_type="fund",
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, amount),
                LedgerEntryRequest(
                    batch_fixture.agent_main_wallet.id, ENTRY_CREDIT, amount
                ),
            ],
            skip_receive_cap=True,
        ),
    )

    rows = [r for r in await _rows(db_session, batch_fixture) if r["transaction_type"] == "fund"]
    assert len(rows) == 1
    assert rows[0]["direction"] == "in"
    assert Decimal(rows[0]["amount"]) == amount
    assert Decimal(rows[0]["transaction_amount"]) == amount
