"""Internal wallet → rewards outbox behavior."""
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    RewardTrigger,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Transaction,
)
from app.shared.models.rewards import OUTBOX_PENDING, RewardOutbox


async def _unguarded_pair(db_session, tenant_id: UUID, currency: str) -> tuple[Account, Account]:
    """Two `operator_adjustment` accounts to form a balanced leg pair.

    Both are unguarded by the balance guard (not financial_wallet / cash_float),
    so a transaction across them needs no pre-funding and trips no max_balance
    cap — letting these tests exercise ONLY the outbox gate, not the money guard.
    Distinct `name`s satisfy the bank-mirror uniqueness index.
    """
    debit = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
        name=f"dr-{uuid4().hex[:8]}",
    )
    credit = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
        name=f"cr-{uuid4().hex[:8]}",
    )
    db_session.add_all([debit, credit])
    await db_session.commit()
    await db_session.refresh(debit)
    await db_session.refresh(credit)
    return debit, credit


async def post_rewardable_txn(
    db_session,
    tenant_id: UUID,
    user_id: UUID,
    txn_type: str,
    amount: Decimal,
    currency: str,
) -> Transaction:
    """Post a balanced transaction carrying a RewardTrigger (money-service path)."""
    debit, credit = await _unguarded_pair(db_session, tenant_id, currency)
    return await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=f"rewardable-{uuid4().hex}",
            transaction_type=txn_type,
            currency=currency,
            amount=amount,
            entries=[
                LedgerEntryRequest(account_id=debit.id, entry_type=ENTRY_DEBIT, amount=amount),
                LedgerEntryRequest(account_id=credit.id, entry_type=ENTRY_CREDIT, amount=amount),
            ],
            reward_trigger=RewardTrigger(
                user_id=user_id,
                transaction_type=txn_type,
                amount=amount,
                currency=currency,
            ),
        ),
    )


async def post_plain_txn(
    db_session,
    tenant_id: UUID,
    txn_type: str,
    amount: Decimal,
    currency: str,
) -> Transaction:
    """Post a balanced transaction with NO RewardTrigger (reward-issuance path)."""
    debit, credit = await _unguarded_pair(db_session, tenant_id, currency)
    return await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=f"plain-{uuid4().hex}",
            transaction_type=txn_type,
            currency=currency,
            amount=amount,
            entries=[
                LedgerEntryRequest(account_id=debit.id, entry_type=ENTRY_DEBIT, amount=amount),
                LedgerEntryRequest(account_id=credit.id, entry_type=ENTRY_CREDIT, amount=amount),
            ],
        ),
    )


async def _outbox_count(db_session, tenant_id: UUID) -> int:
    """Count reward_outbox rows for a tenant."""
    return (
        await db_session.execute(
            select(func.count()).select_from(RewardOutbox).where(
                RewardOutbox.tenant_id == tenant_id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_outbox_row_is_tenant_scoped(db_session, tenant_factory):
    """Verify a reward-outbox row for one tenant is invisible to another tenant."""
    # Two independent tenants — the outbox row belongs to tenant A only.
    tenant_a = await tenant_factory(business_type="both")
    tenant_b = await tenant_factory(business_type="both")

    # The outbox FK targets transactions.id, so a real transaction must exist.
    # A minimal row (only the NOT NULL columns without defaults) satisfies it;
    # we are asserting tenant isolation, not exercising post_transaction.
    txn = Transaction(
        tenant_id=tenant_a.id,
        idempotency_key=f"outbox-test-{uuid4().hex}",
        transaction_type="p2p",
        amount=100,
        currency="ZAR",
    )
    db_session.add(txn)
    await db_session.flush()

    outbox = RewardOutbox(
        tenant_id=tenant_a.id,
        user_id=uuid4(),
        transaction_id=txn.id,
        transaction_type="p2p",
        amount=100,
        currency="ZAR",
    )
    db_session.add(outbox)
    await db_session.commit()

    # Querying under tenant B's id must return nothing.
    seen_by_b = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == tenant_b.id)
        )
    ).scalars().all()
    assert seen_by_b == []

    # Tenant A sees exactly its own pending row.
    seen_by_a = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == tenant_a.id)
        )
    ).scalars().all()
    assert len(seen_by_a) == 1
    assert seen_by_a[0].id == outbox.id
    assert seen_by_a[0].status == OUTBOX_PENDING


def test_reward_trigger_optional_defaults_none():
    """Verify a caller that omits reward_trigger gets no reward loop by default."""
    # PostTransactionRequest is a frozen dataclass (not a Pydantic model), so the
    # default is read via the dataclass field descriptor rather than model_fields.
    import dataclasses

    fields = {f.name: f for f in dataclasses.fields(PostTransactionRequest)}
    assert "reward_trigger" in fields
    assert fields["reward_trigger"].default is None


@pytest.mark.asyncio
async def test_outbox_written_only_in_both_mode(db_session, tenant_factory, user_factory):
    """Verify a rewardable wallet transaction enqueues a reward only in 'both' mode."""
    # 'both' tenant: the trigger lands exactly one pending outbox row.
    both = await tenant_factory(business_type="both")
    both_user = await user_factory(both)
    txn = await post_rewardable_txn(
        db_session, both.id, both_user.id, "cash_in", Decimal("100"), "ZAR"
    )
    rows = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == both.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.transaction_id == txn.id
    assert row.user_id == both_user.id
    assert row.transaction_type == "cash_in"
    assert row.amount == Decimal("100")
    assert row.currency == "ZAR"
    assert row.status == OUTBOX_PENDING

    # 'wallet' tenant: same rewardable transaction writes NO outbox row.
    wallet = await tenant_factory(business_type="wallet")
    wallet_user = await user_factory(wallet)
    await post_rewardable_txn(
        db_session, wallet.id, wallet_user.id, "cash_in", Decimal("100"), "ZAR"
    )
    assert await _outbox_count(db_session, wallet.id) == 0


@pytest.mark.asyncio
async def test_no_outbox_without_reward_trigger(db_session, tenant_factory, user_factory):
    """Verify a reward-issuance-style transaction never re-triggers rewards (no loop)."""
    # Even in 'both' mode, a transaction WITHOUT a reward_trigger enqueues nothing —
    # this is what keeps reward payouts from looping back into the evaluator.
    both = await tenant_factory(business_type="both")
    await user_factory(both)
    await post_plain_txn(db_session, both.id, "reward_issuance", Decimal("100"), "ZAR")
    assert await _outbox_count(db_session, both.id) == 0
