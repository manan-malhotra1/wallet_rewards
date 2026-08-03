"""Internal wallet → rewards outbox behavior."""
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    RewardTrigger,
    post_transaction,
)
from app.modules.rewards.outbox import attempt_immediate, recon_sweep_async
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    RewardEvent,
    Rule,
    Transaction,
)
from app.shared.models.rewards import OUTBOX_PENDING, OUTBOX_PROCESSED, RewardOutbox


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


@pytest.mark.asyncio
async def test_idempotent_retry_writes_no_second_outbox(db_session, tenant_factory, user_factory):
    """Verify replaying a rewardable transaction never double-enqueues its reward."""
    # Financial idempotency: a retried idempotency_key must return the original
    # transaction WITHOUT writing a second outbox row (the early return at
    # post_transaction service.py:194 short-circuits before the outbox insert).
    both = await tenant_factory(business_type="both")
    user = await user_factory(both)
    debit, credit = await _unguarded_pair(db_session, both.id, "ZAR")
    request = PostTransactionRequest(
        tenant_id=both.id,
        idempotency_key="rewardable-retry-1",
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal("100"),
        entries=[
            LedgerEntryRequest(
                account_id=debit.id, entry_type=ENTRY_DEBIT, amount=Decimal("100")
            ),
            LedgerEntryRequest(
                account_id=credit.id, entry_type=ENTRY_CREDIT, amount=Decimal("100")
            ),
        ],
        reward_trigger=RewardTrigger(
            user_id=user.id,
            transaction_type="cash_in",
            amount=Decimal("100"),
            currency="ZAR",
        ),
    )
    first = await post_transaction(db_session, request)
    assert await _outbox_count(db_session, both.id) == 1

    # Replay with the SAME idempotency_key — original txn returned, no new row.
    second = await post_transaction(db_session, request)
    assert second.id == first.id
    assert await _outbox_count(db_session, both.id) == 1


@pytest.mark.asyncio
async def test_non_rewardable_type_writes_no_outbox(db_session, tenant_factory, user_factory):
    """Verify a non-rewardable trigger type is rejected by the allowlist (no reward)."""
    # Defense-in-depth: even in 'both' mode with a reward_trigger present, a type
    # outside REWARDABLE_TYPES (e.g. reward_issuance) must enqueue nothing.
    both = await tenant_factory(business_type="both")
    user = await user_factory(both)
    debit, credit = await _unguarded_pair(db_session, both.id, "ZAR")
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=both.id,
            idempotency_key=f"non-rewardable-{uuid4().hex}",
            transaction_type="reward_issuance",
            currency="ZAR",
            amount=Decimal("100"),
            entries=[
                LedgerEntryRequest(
                    account_id=debit.id, entry_type=ENTRY_DEBIT, amount=Decimal("100")
                ),
                LedgerEntryRequest(
                    account_id=credit.id, entry_type=ENTRY_CREDIT, amount=Decimal("100")
                ),
            ],
            reward_trigger=RewardTrigger(
                user_id=user.id,
                transaction_type="reward_issuance",  # NOT in REWARDABLE_TYPES
                amount=Decimal("100"),
                currency="ZAR",
            ),
        ),
    )
    assert await _outbox_count(db_session, both.id) == 0


@pytest.mark.asyncio
async def test_evaluate_and_issue_firings_issues_reward_for_seeded_rule(
    db_session,
    test_tenant,
    test_user,
    user_points,
    system_points_account,
):
    """Verify the shared issuance core rewards a user when an active rule fires."""
    # This exercises evaluate_and_issue_firings directly (the reusable core the
    # external Kafka path and the internal wallet outbox drainer both call),
    # independent of the HMAC/dedup wrapper in process_external_event.
    # Seed an active first_time rule matching the event's transaction_type.
    rule = Rule(
        tenant_id=test_tenant.id,
        name="first p2p",
        rule_type="first_time",
        transaction_type="p2p",
        reward_type="points",
        reward_value=Decimal("100"),
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    event = NormalisedEvent(
        event_id="txn-test-1",
        source_key="internal:wallet",
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        transaction_type="p2p",
        amount=Decimal("100"),
        currency="ZAR",
        merchant_id=None,
        timestamp=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
    )

    issued = await evaluate_and_issue_firings(db_session, event)
    await db_session.commit()

    # Exactly one firing, carrying the configured reward value.
    assert len(issued) == 1
    assert issued[0].rule_id == rule.id
    assert issued[0].reward_type == "points"
    assert issued[0].reward_value == Decimal("100")

    # A reward_events row was persisted for this user + rule + triggering event.
    reward = (
        await db_session.execute(
            select(RewardEvent).where(
                RewardEvent.user_id == test_user.id,
                RewardEvent.rule_id == rule.id,
                RewardEvent.triggering_event_id == "txn-test-1",
            )
        )
    ).scalar_one()
    assert reward.reward_value == Decimal("100")


async def _seed_first_time_p2p_rule(db_session, tenant_id: UUID) -> Rule:
    """Seed an active first_time p2p points rule for a tenant."""
    rule = Rule(
        tenant_id=tenant_id,
        name="first p2p",
        rule_type="first_time",
        transaction_type="p2p",
        reward_type="points",
        reward_value=Decimal("100"),
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


async def _reward_event_count(db_session, user_id: UUID, rule_id: UUID) -> int:
    """Count reward_events rows for a (user, rule) pair."""
    return (
        await db_session.execute(
            select(func.count())
            .select_from(RewardEvent)
            .where(RewardEvent.user_id == user_id, RewardEvent.rule_id == rule_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_attempt_immediate_issues_and_is_idempotent(
    db_session,
    session_factory,
    test_tenant,
    test_user,
    user_points,
    system_points_account,
):
    """Verify the immediate drain rewards the user once and never double-issues on replay."""
    # A matching first_time p2p rule + a rewardable p2p txn that enqueues one
    # PENDING outbox row (the money-service path via post_transaction).
    rule = await _seed_first_time_p2p_rule(db_session, test_tenant.id)
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    # First drain: the rule fires once and the row is marked PROCESSED.
    firings = await attempt_immediate(
        session_factory, tenant_id=test_tenant.id, user_id=test_user.id
    )
    assert len(firings) == 1
    assert firings[0].rule_id == rule.id
    assert await _reward_event_count(db_session, test_user.id, rule.id) == 1
    row = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert row.status == OUTBOX_PROCESSED

    # Second drain: the row is no longer PENDING, so nothing is claimed and the
    # single reward_event stands (idempotent — no double issuance).
    again = await attempt_immediate(
        session_factory, tenant_id=test_tenant.id, user_id=test_user.id
    )
    assert again == []
    assert await _reward_event_count(db_session, test_user.id, rule.id) == 1


@pytest.mark.asyncio
async def test_recon_sweep_drains_pending(
    db_session,
    session_factory,
    test_tenant,
    test_user,
    user_points,
    system_points_account,
):
    """Verify the recon sweep drains a leftover PENDING outbox row and issues its reward."""
    # One PENDING row the immediate attempt never ran (simulating a crash /
    # transient miss) — the sweep is the durability safety net that catches it.
    rule = await _seed_first_time_p2p_rule(db_session, test_tenant.id)
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    processed = await recon_sweep_async(session_factory)
    assert processed == 1
    assert await _reward_event_count(db_session, test_user.id, rule.id) == 1
    row = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
        )
    ).scalar_one()
    assert row.status == OUTBOX_PROCESSED
