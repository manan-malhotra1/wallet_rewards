"""Internal wallet → rewards outbox behavior."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.modules.accounts.service import derive_balance
from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    RewardTrigger,
    post_transaction,
)
from app.modules.rewards.outbox import (
    MAX_ATTEMPTS,
    attempt_immediate,
    recon_sweep_async,
)
from app.modules.rewards.service import POINTS_CURRENCY
from app.shared.exceptions import UserFinancialWalletMissing, UserPointsAccountMissing
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_POINTS,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    RewardEvent,
    Rule,
    Transaction,
)
from app.shared.models.rewards import (
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSED,
    RewardOutbox,
)


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
            select(func.count())
            .select_from(RewardOutbox)
            .where(RewardOutbox.tenant_id == tenant_id)
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
        (
            await db_session.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == tenant_b.id)
            )
        )
        .scalars()
        .all()
    )
    assert seen_by_b == []

    # Tenant A sees exactly its own pending row.
    seen_by_a = (
        (
            await db_session.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == tenant_a.id)
            )
        )
        .scalars()
        .all()
    )
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
        (await db_session.execute(select(RewardOutbox).where(RewardOutbox.tenant_id == both.id)))
        .scalars()
        .all()
    )
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
            LedgerEntryRequest(account_id=debit.id, entry_type=ENTRY_DEBIT, amount=Decimal("100")),
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
    again = await attempt_immediate(session_factory, tenant_id=test_tenant.id, user_id=test_user.id)
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


@pytest.mark.asyncio
async def test_attempt_immediate_is_fail_open_on_issue_error(
    db_session,
    session_factory,
    test_tenant,
    test_user,
    monkeypatch,
):
    """Verify a reward issuance failure never surfaces on the money path."""

    # attempt_immediate runs AFTER the wallet txn committed, so a reward hiccup
    # must be swallowed. Force the issuance core to blow up mid-drain.
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("issuance backend down")

    monkeypatch.setattr("app.modules.rewards.outbox.evaluate_and_issue_firings", _boom)

    # One PENDING outbox row (no rule needed — issuance is patched to raise).
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    # Must return normally with no firings — never re-raise onto the caller.
    firings = await attempt_immediate(
        session_factory, tenant_id=test_tenant.id, user_id=test_user.id
    )
    assert firings == []

    # The row is marked FAILED with bookkeeping persisted. Read it in a fresh
    # session so we see the committed state, not db_session's stale identity-map
    # copy from post_rewardable_txn.
    async with session_factory() as verify:
        row = (
            await verify.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
            )
        ).scalar_one()
        assert row.status == OUTBOX_FAILED
        assert row.attempts == 1
        assert row.last_error is not None
        assert "issuance backend down" in row.last_error


@pytest.mark.asyncio
async def test_issue_immediate_points_is_absolutely_fail_open(
    db_session,
    monkeypatch,
):
    """Verify a drainer failure never breaks a payment that already committed."""
    # issue_immediate_points runs AFTER the money-path commit. A failure ANYWHERE
    # in its body — the session checkout, the sessionmaker construction, or the
    # FOR UPDATE fetch (all OUTSIDE attempt_immediate's inner per-row guard) —
    # must degrade to "0 points earned", never propagate as a 500 for a succeeded
    # payment. Force attempt_immediate (which owns the checkout + fetch) to raise
    # a pool-timeout-style error and assert the helper still returns an int of 0.
    from app.modules.rewards import outbox as outbox_mod

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("pool timeout on session checkout")

    monkeypatch.setattr(outbox_mod, "attempt_immediate", _boom)

    earned = await outbox_mod.issue_immediate_points(db_session, tenant_id=uuid4(), user_id=uuid4())
    assert earned == 0


@pytest.mark.asyncio
async def test_recon_sweep_auto_provisions_points_account_for_first_time_earner(
    db_session,
    session_factory,
    test_tenant,
    test_user,
):
    """Verify a first-time earner who holds no points account still gets rewarded."""
    # Neither `user_points` nor `system_points_account` is requested: this user
    # has NO points account and the tenant has no system issuance master yet.
    # Draining the outbox must auto-provision both and land the reward — not fail
    # and leave a poisoned row. This is the end-to-end shape of the bug fix.
    rule = await _seed_first_time_p2p_rule(db_session, test_tenant.id)
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    processed = await recon_sweep_async(session_factory)
    assert processed == 1
    assert await _reward_event_count(db_session, test_user.id, rule.id) == 1

    # A PTS points account now exists for the user and carries the credited reward.
    async with session_factory() as verify:
        account = (
            await verify.execute(
                select(Account).where(
                    Account.tenant_id == test_tenant.id,
                    Account.user_id == test_user.id,
                    Account.account_type == ACCOUNT_TYPE_POINTS,
                )
            )
        ).scalar_one()
        assert account.currency == POINTS_CURRENCY
        balance, _ = await derive_balance(verify, account.id)
        assert balance == Decimal("100")

        row = (
            await verify.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
            )
        ).scalar_one()
        assert row.status == OUTBOX_PROCESSED


@pytest.mark.asyncio
async def test_attempt_immediate_marks_processed_noop_on_unprovisionable(
    db_session,
    session_factory,
    test_tenant,
    test_user,
    monkeypatch,
):
    """Verify an unrewardable-account drain resolves the row instead of poisoning it."""

    # Defense-in-depth: if issuance genuinely cannot land a reward (no account and
    # none provisionable), the immediate drain must mark the row PROCESSED — not
    # FAILED — so the recon sweep never retries a no-op to MAX_ATTEMPTS.
    async def _raise_unprovisionable(*_args, **_kwargs):
        raise UserPointsAccountMissing()

    monkeypatch.setattr(
        "app.modules.rewards.outbox.evaluate_and_issue_firings", _raise_unprovisionable
    )
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    firings = await attempt_immediate(
        session_factory, tenant_id=test_tenant.id, user_id=test_user.id
    )
    assert firings == []

    async with session_factory() as verify:
        row = (
            await verify.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
            )
        ).scalar_one()
        # Resolved as a benign no-op: PROCESSED, not FAILED; attempts NOT burned.
        assert row.status == OUTBOX_PROCESSED
        assert row.processed_at is not None
        assert row.attempts == 0


@pytest.mark.asyncio
async def test_recon_sweep_marks_processed_noop_on_unprovisionable(
    db_session,
    session_factory,
    test_tenant,
    test_user,
    monkeypatch,
):
    """Verify the recon sweep resolves an unrewardable row rather than retrying forever."""

    async def _raise_unprovisionable(*_args, **_kwargs):
        raise UserPointsAccountMissing()

    monkeypatch.setattr(
        "app.modules.rewards.outbox.evaluate_and_issue_firings", _raise_unprovisionable
    )
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    # Counted as processed — the row is no longer outstanding after a no-op.
    processed = await recon_sweep_async(session_factory)
    assert processed == 1

    async with session_factory() as verify:
        row = (
            await verify.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
            )
        ).scalar_one()
        assert row.status == OUTBOX_PROCESSED
        assert row.attempts == 0


@pytest.mark.asyncio
async def test_attempt_immediate_fails_and_retries_on_missing_financial_wallet(
    db_session,
    session_factory,
    test_tenant,
    test_user,
    monkeypatch,
):
    """Verify a missing financial wallet FAILS (retries) — owed cashback is never dropped.

    A missing financial_wallet is NOT a benign no-op: financial wallets aren't
    auto-provisioned, so a walletless cashback is legitimately owed money that CAN
    be paid once the wallet exists. It must fall through to FAILED (retry +
    stuck-row alert), not be silently marked PROCESSED.
    """

    async def _raise_missing_wallet(*_args, **_kwargs):
        raise UserFinancialWalletMissing()

    monkeypatch.setattr(
        "app.modules.rewards.outbox.evaluate_and_issue_firings", _raise_missing_wallet
    )
    await post_rewardable_txn(
        db_session, test_tenant.id, test_user.id, "p2p", Decimal("100"), "ZAR"
    )

    firings = await attempt_immediate(
        session_factory, tenant_id=test_tenant.id, user_id=test_user.id
    )
    assert firings == []

    async with session_factory() as verify:
        row = (
            await verify.execute(
                select(RewardOutbox).where(RewardOutbox.tenant_id == test_tenant.id)
            )
        ).scalar_one()
        # Retryable, NOT a silent drop: FAILED with a burned attempt + recorded error.
        assert row.status == OUTBOX_FAILED
        assert row.attempts == 1
        assert row.last_error is not None


@pytest.mark.asyncio
async def test_recon_skips_poison_rows_at_max_attempts(
    db_session,
    session_factory,
    test_tenant,
):
    """Verify the recon sweep leaves a row that has exhausted its retries untouched."""
    # A row already at MAX_ATTEMPTS is a poison message: the sweep must not
    # claim it (it surfaces as a stuck-row alert instead), so nothing is drained.
    txn = Transaction(
        tenant_id=test_tenant.id,
        idempotency_key=f"poison-{uuid4().hex}",
        transaction_type="p2p",
        amount=100,
        currency="ZAR",
    )
    db_session.add(txn)
    await db_session.flush()
    poison = RewardOutbox(
        tenant_id=test_tenant.id,
        user_id=uuid4(),
        transaction_id=txn.id,
        transaction_type="p2p",
        amount=100,
        currency="ZAR",
        status=OUTBOX_FAILED,
        attempts=MAX_ATTEMPTS,
        last_error="prior failures",
    )
    db_session.add(poison)
    await db_session.commit()

    poison_id = poison.id  # capture before opening the verify session

    processed = await recon_sweep_async(session_factory)
    assert processed == 0

    # Untouched: still FAILED at MAX_ATTEMPTS, never processed. Read in a fresh
    # session to avoid db_session's stale identity-map copy.
    async with session_factory() as verify:
        row = (
            await verify.execute(select(RewardOutbox).where(RewardOutbox.id == poison_id))
        ).scalar_one()
        assert row.status == OUTBOX_FAILED
        assert row.attempts == MAX_ATTEMPTS
        assert row.processed_at is None


@pytest.mark.skip(
    reason="reversal claw-back is a designed-but-unbuilt hook; reversals don't "
    "exist yet (spec 2026-08-03 §4)"
)
@pytest.mark.asyncio
async def test_reversal_claws_back_reward():
    # When reversals land: a reversal txn emits a reward_outbox row; the handler
    # looks up the original reward_events (via transaction_id), posts an append-only
    # claw-back to system_points_issuance, and decrements user_rule_progress.
    # reward_outbox.transaction_id is the hook.
    ...
