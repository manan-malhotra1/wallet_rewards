"""Batch evaluator tests (spec §4) — criteria-driven segment membership recompute.

`_wallet_account` / `_wallet_txn` below mirror the wallet-attributed activity
factories in `tests/segments/test_metrics.py` (duplicated locally rather than
imported, per this repo's test-isolation convention) so `txn_count`-style
criteria conditions see real COMPLETED transactions that touched the user's
own `financial_wallet` account.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments import evaluator
from app.modules.segments.criteria import SegmentCriteria
from app.modules.segments.evaluator import preview_criteria, recompute_tenant
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    TXN_STATUS_COMPLETED,
    USER_SEGMENT_SOURCE_CRITERIA,
    USER_SEGMENT_SOURCE_MANUAL,
    Account,
    AuditLog,
    LedgerEntry,
    Segment,
    SegmentGroup,
    Tenant,
    Transaction,
    User,
    UserSegment,
)


async def _wallet_account(
    db_session: AsyncSession, tenant_id: UUID, user_id: UUID | None, currency: str = "ZAR"
) -> Account:
    """Create + flush a financial_wallet account (see test_metrics.py's twin)."""
    account = Account(
        tenant_id=tenant_id,
        user_id=user_id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
    )
    db_session.add(account)
    await db_session.flush()
    return account


async def _wallet_txn(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    debit_account: Account,
    credit_account: Account,
    amount: str = "10",
    txn_type: str = "p2p",
    days_ago: int = 0,
    currency: str = "ZAR",
) -> Transaction:
    """Create a COMPLETED transaction with a DEBIT + CREDIT leg on two wallets.

    Minimal local copy of `test_metrics.py::_wallet_txn` — only the params
    the evaluator tests actually use (no `initiated_by` override needed here,
    since the evaluator only reads wallet-attributed metric values, not
    `Transaction.initiated_by`).
    """
    created_at = datetime.now(UTC) - timedelta(days=days_ago)
    txn = Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"k-{uuid4()}",
        transaction_type=txn_type,
        status=TXN_STATUS_COMPLETED,
        initiated_by=debit_account.user_id,
        amount=Decimal(amount),
        currency=currency,
        created_at=created_at,
    )
    db_session.add(txn)
    await db_session.flush()
    db_session.add_all(
        [
            LedgerEntry(
                transaction_id=txn.id,
                account_id=debit_account.id,
                entry_type=ENTRY_DEBIT,
                amount=Decimal(amount),
                currency=currency,
                status=ENTRY_STATUS_COMPLETED,
                created_at=created_at,
            ),
            LedgerEntry(
                transaction_id=txn.id,
                account_id=credit_account.id,
                entry_type=ENTRY_CREDIT,
                amount=Decimal(amount),
                currency=currency,
                status=ENTRY_STATUS_COMPLETED,
                created_at=created_at,
            ),
        ]
    )
    await db_session.flush()
    return txn


async def _txn_count_segment(
    db_session: AsyncSession,
    tenant_id: UUID,
    group: SegmentGroup,
    *,
    name: str,
    priority: int,
    gte: int,
) -> Segment:
    """Create + flush a dynamic segment with a single `txn_count gte N` condition."""
    segment = Segment(
        tenant_id=tenant_id,
        group_id=group.id,
        name=name,
        priority=priority,
        criteria={"v": 1, "op": "AND", "conditions": [{"metric": "txn_count", "gte": gte}]},
    )
    db_session.add(segment)
    await db_session.flush()
    return segment


async def _user_segment_count(db_session: AsyncSession) -> int:
    """Total row count of `user_segments`, for before/after write assertions."""
    result = await db_session.execute(select(func.count()).select_from(UserSegment))
    return int(result.scalar_one())


async def _audit_count_for_segment(db_session: AsyncSession, segment_id: UUID) -> int:
    """Count `segment.recomputed` audit_log rows written for one segment."""
    result = await db_session.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "segment.recomputed", AuditLog.entity_id == str(segment_id))
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_highest_priority_wins_within_group(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Gold (gte 3, prio 3) and Bronze (gte 1, prio 1) in one group: a user with
    3 wallet transactions matches both, but exclusivity keeps them in Gold only."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    gold = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Gold", priority=3, gte=3
    )
    bronze = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Bronze", priority=1, gte=1
    )

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    for _ in range(3):
        await _wallet_txn(
            db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
        )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert summary[gold.id] == {"added": 1, "removed": 0, "member_count": 1}
    assert summary[bronze.id] == {"added": 0, "removed": 0, "member_count": 0}

    gold_members = (
        (await db_session.execute(select(UserSegment).where(UserSegment.segment_id == gold.id)))
        .scalars()
        .all()
    )
    assert [m.user_id for m in gold_members] == [test_user.id]
    bronze_members = (
        (await db_session.execute(select(UserSegment).where(UserSegment.segment_id == bronze.id)))
        .scalars()
        .all()
    )
    assert bronze_members == []


@pytest.mark.asyncio
async def test_manual_memberships_survive_recompute(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A manual member of Gold with zero activity stays a member after recompute."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    gold = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Gold", priority=3, gte=3
    )
    db_session.add(
        UserSegment(user_id=test_user.id, segment_id=gold.id, source=USER_SEGMENT_SOURCE_MANUAL)
    )
    await db_session.flush()

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert summary[gold.id] == {"added": 0, "removed": 0, "member_count": 0}
    row = (
        await db_session.execute(select(UserSegment).where(UserSegment.segment_id == gold.id))
    ).scalar_one()
    assert row.source == USER_SEGMENT_SOURCE_MANUAL


@pytest.mark.asyncio
async def test_manual_member_who_also_matches_does_not_violate_unique(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A user manually in Bronze who also matches it by criteria: recompute
    succeeds (no IntegrityError), the row stays source=manual, and the summary
    counts them in neither `added` nor `removed`."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    bronze = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Bronze", priority=1, gte=1
    )
    db_session.add(
        UserSegment(user_id=test_user.id, segment_id=bronze.id, source=USER_SEGMENT_SOURCE_MANUAL)
    )
    await db_session.flush()

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert summary[bronze.id] == {"added": 0, "removed": 0, "member_count": 1}
    row = (
        await db_session.execute(select(UserSegment).where(UserSegment.segment_id == bronze.id))
    ).scalar_one()
    assert row.source == USER_SEGMENT_SOURCE_MANUAL


@pytest.mark.asyncio
async def test_recompute_is_idempotent_and_moves_users_between_tiers(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """First run adds to Bronze; a second run is a no-op; adding enough
    activity for Gold moves the user there and removes them from Bronze."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    gold = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Gold", priority=3, gte=3
    )
    bronze = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Bronze", priority=1, gte=1
    )
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    first = await recompute_tenant(db_session, test_tenant.id)
    assert first[bronze.id] == {"added": 1, "removed": 0, "member_count": 1}
    assert first[gold.id] == {"added": 0, "removed": 0, "member_count": 0}
    assert await _audit_count_for_segment(db_session, bronze.id) == 1

    second = await recompute_tenant(db_session, test_tenant.id)
    assert second[bronze.id] == {"added": 0, "removed": 0, "member_count": 1}
    assert second[gold.id] == {"added": 0, "removed": 0, "member_count": 0}
    # No-change rerun must NOT write a second audit row for bronze.
    assert await _audit_count_for_segment(db_session, bronze.id) == 1

    for _ in range(2):
        await _wallet_txn(
            db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
        )

    third = await recompute_tenant(db_session, test_tenant.id)
    assert third[gold.id] == {"added": 1, "removed": 0, "member_count": 1}
    assert third[bronze.id] == {"added": 0, "removed": 1, "member_count": 0}
    # Bronze changed again (a removal) -> a second audit row; Gold's first
    # ever change -> exactly one audit row so far.
    assert await _audit_count_for_segment(db_session, bronze.id) == 2
    assert await _audit_count_for_segment(db_session, gold.id) == 1


@pytest.mark.asyncio
async def test_static_segments_untouched(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A criteria-NULL segment is absent from the summary and keeps
    `last_evaluated_at` NULL, even alongside a dynamic segment that changes."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="General")
    db_session.add(group)
    await db_session.flush()
    static_segment = Segment(
        tenant_id=test_tenant.id, group_id=group.id, name="hand-picked", criteria=None
    )
    db_session.add(static_segment)
    dynamic_group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(dynamic_group)
    await db_session.flush()
    dynamic_segment = await _txn_count_segment(
        db_session, test_tenant.id, dynamic_group, name="Bronze", priority=1, gte=1
    )
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert static_segment.id not in summary
    assert dynamic_segment.id in summary
    await db_session.refresh(static_segment)
    assert static_segment.last_evaluated_at is None


@pytest.mark.asyncio
async def test_lte_only_criteria_covers_inactive_users(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """`points_balance lte 0` in its own group: a user with NO activity at all
    (no points account, no ledger rows) becomes a member — the absent-user
    universe rule, since such a user contributes zero rows to the points
    metric's value map and would otherwise never be considered."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Dormant Points")
    db_session.add(group)
    await db_session.flush()
    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="No Points",
        priority=1,
        criteria={"v": 1, "op": "AND", "conditions": [{"metric": "points_balance", "lte": 0}]},
    )
    db_session.add(segment)
    await db_session.flush()

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert summary[segment.id] == {"added": 1, "removed": 0, "member_count": 1}
    row = (
        await db_session.execute(select(UserSegment).where(UserSegment.segment_id == segment.id))
    ).scalar_one()
    assert row.user_id == test_user.id
    assert row.source == USER_SEGMENT_SOURCE_CRITERIA


@pytest.mark.asyncio
async def test_cross_tenant_isolation(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    other_tenant: Tenant,
    user_factory: Any,
) -> None:
    """Recomputing test_tenant touches no other_tenant memberships and vice versa."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    other_group = SegmentGroup(tenant_id=other_tenant.id, name="Customer Loyalty")
    db_session.add(other_group)
    await db_session.flush()
    segment = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Bronze", priority=1, gte=1
    )
    other_segment = await _txn_count_segment(
        db_session, other_tenant.id, other_group, name="Bronze", priority=1, gte=1
    )

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    other_user = await user_factory(other_tenant)
    other_wallet = await _wallet_account(
        db_session, other_tenant.id, other_user.id, currency=other_tenant.base_currency
    )
    other_counterpart = await _wallet_account(
        db_session, other_tenant.id, None, currency=other_tenant.base_currency
    )
    await _wallet_txn(
        db_session,
        other_tenant.id,
        debit_account=other_wallet,
        credit_account=other_counterpart,
        currency=other_tenant.base_currency,
    )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert segment.id in summary
    assert other_segment.id not in summary
    other_members = (
        (
            await db_session.execute(
                select(UserSegment).where(UserSegment.segment_id == other_segment.id)
            )
        )
        .scalars()
        .all()
    )
    assert other_members == []

    other_summary = await recompute_tenant(db_session, other_tenant.id)

    assert other_summary[other_segment.id] == {"added": 1, "removed": 0, "member_count": 1}
    test_tenant_members = (
        (await db_session.execute(select(UserSegment).where(UserSegment.segment_id == segment.id)))
        .scalars()
        .all()
    )
    assert [m.user_id for m in test_tenant_members] == [test_user.id]


@pytest.mark.asyncio
async def test_preview_counts_without_writing(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    user_factory: Any,
) -> None:
    """Preview returns the expected match count and writes no rows."""
    user_b = await user_factory(test_tenant)
    wallet_b = await _wallet_account(db_session, test_tenant.id, user_b.id)
    user_c = await user_factory(test_tenant)
    await _wallet_account(db_session, test_tenant.id, user_c.id)  # no activity

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=wallet_b, credit_account=counterpart
    )

    before = await _user_segment_count(db_session)
    criteria = SegmentCriteria.model_validate(
        {"v": 1, "op": "AND", "conditions": [{"metric": "txn_count", "gte": 1}]}
    )

    count = await preview_criteria(db_session, test_tenant.id, criteria)

    assert count == 2
    assert await _user_segment_count(db_session) == before


@pytest.mark.asyncio
async def test_audit_row_written_on_change(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A recompute that changes membership writes a `segment.recomputed` audit row."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    segment = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Bronze", priority=1, gte=1
    )
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    await recompute_tenant(db_session, test_tenant.id)

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "segment.recomputed",
                AuditLog.entity_id == str(segment.id),
            )
        )
    ).scalar_one()
    assert audit_row.entity_type == "segment"
    assert audit_row.actor_type == "system"
    assert audit_row.tenant_id == test_tenant.id
    assert audit_row.after_state == {"added": 1, "removed": 0, "member_count": 1}


@pytest.mark.asyncio
async def test_poison_criteria_segment_is_skipped_entirely(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    user_factory: Any,
) -> None:
    """A segment whose stored `criteria` fails DSL validation (inserted
    directly via the ORM, bypassing the Pydantic layer — e.g. a hand-edited
    row or DSL version drift) is skipped ENTIRELY: omitted from the summary,
    its membership left completely untouched, and `last_evaluated_at` stays
    NULL. A good segment in a DIFFERENT group still recomputes normally.

    The "membership untouched" claim is made non-vacuous by seeding a
    `source='criteria'` row for a user who would NOT match if the criteria
    were re-evaluated fresh — proving the row survives because the segment
    is skipped, not merely because nothing would have changed anyway.

    Note: this repo has no existing precedent for asserting structlog output
    via `caplog` (structlog here isn't wired through stdlib `logging`), so
    per the coordinator's guidance this test verifies the poison-isolation
    behaviour through its observable effect (summary omission + untouched
    membership) rather than asserting on the warning log line itself. If a
    future test DOES want to assert the log line, `structlog.testing.
    capture_logs()` works out of the box with zero configuration wiring
    (unlike `caplog`, which needs stdlib-`logging` integration this repo
    doesn't have).
    """
    poison_group = SegmentGroup(tenant_id=test_tenant.id, name="Poisoned Group")
    db_session.add(poison_group)
    await db_session.flush()
    poisoned = Segment(
        tenant_id=test_tenant.id,
        group_id=poison_group.id,
        name="Poisoned",
        priority=1,
        # Empty `conditions` fails SegmentCriteria's min_length=1 — a DSL-
        # invalid document that could only land here by bypassing validation
        # (e.g. direct ORM/SQL manipulation), not through the service layer.
        criteria={"v": 1, "op": "AND", "conditions": []},
    )
    db_session.add(poisoned)
    await db_session.flush()
    # A stale criteria-source row for a user with ZERO activity — this user
    # would not match any real "has activity" criteria, so if the poisoned
    # segment were (incorrectly) re-evaluated with desired=empty, this row
    # would be deleted. Its survival proves the skip is a true no-op.
    stale_member = await user_factory(test_tenant)
    db_session.add(
        UserSegment(
            user_id=stale_member.id, segment_id=poisoned.id, source=USER_SEGMENT_SOURCE_CRITERIA
        )
    )
    await db_session.flush()

    good_group = SegmentGroup(tenant_id=test_tenant.id, name="Good Group")
    db_session.add(good_group)
    await db_session.flush()
    good = await _txn_count_segment(
        db_session, test_tenant.id, good_group, name="Bronze", priority=1, gte=1
    )
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert poisoned.id not in summary
    assert good.id in summary
    assert summary[good.id] == {"added": 1, "removed": 0, "member_count": 1}

    poisoned_members = (
        (await db_session.execute(select(UserSegment).where(UserSegment.segment_id == poisoned.id)))
        .scalars()
        .all()
    )
    assert [m.user_id for m in poisoned_members] == [stale_member.id]
    assert poisoned_members[0].source == USER_SEGMENT_SOURCE_CRITERIA
    await db_session.refresh(poisoned)
    assert poisoned.last_evaluated_at is None


@pytest.mark.asyncio
async def test_poisoned_group_quarantines_healthy_sibling_segment(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A poisoned Gold alongside a healthy Bronze in the SAME exclusive group
    quarantines the WHOLE group: Bronze is NOT added even though the user
    matches it, no new rows land in that group at all, and a segment in an
    UNRELATED group still recomputes normally.

    This is the double-reward-path regression this quarantine prevents: if
    only Gold were skipped, Bronze would stop being suppressed by Gold (whose
    real match outcome is now unknown) and the user could end up holding two
    tiers of one lens simultaneously.
    """
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    poisoned_gold = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="Gold",
        priority=3,
        criteria={"v": 1, "op": "AND", "conditions": []},
    )
    db_session.add(poisoned_gold)
    healthy_bronze = await _txn_count_segment(
        db_session, test_tenant.id, group, name="Bronze", priority=1, gte=1
    )

    other_group = SegmentGroup(tenant_id=test_tenant.id, name="Unrelated")
    db_session.add(other_group)
    await db_session.flush()
    unrelated = await _txn_count_segment(
        db_session, test_tenant.id, other_group, name="Active", priority=1, gte=1
    )

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert poisoned_gold.id not in summary
    assert healthy_bronze.id not in summary
    assert unrelated.id in summary
    assert summary[unrelated.id] == {"added": 1, "removed": 0, "member_count": 1}

    group_members = (
        (
            await db_session.execute(
                select(UserSegment).where(
                    UserSegment.segment_id.in_([poisoned_gold.id, healthy_bronze.id])
                )
            )
        )
        .scalars()
        .all()
    )
    assert group_members == []
    await db_session.refresh(healthy_bronze)
    assert healthy_bronze.last_evaluated_at is None


@pytest.mark.asyncio
async def test_user_wins_two_different_groups_simultaneously(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A user can win a segment in TWO independent groups at once — exclusivity
    is scoped per group_id, not tenant-wide (the central multi-group claim)."""
    loyalty_group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    dormant_group = SegmentGroup(tenant_id=test_tenant.id, name="Dormant Points")
    db_session.add_all([loyalty_group, dormant_group])
    await db_session.flush()

    bronze = await _txn_count_segment(
        db_session, test_tenant.id, loyalty_group, name="Bronze", priority=1, gte=1
    )
    no_points = Segment(
        tenant_id=test_tenant.id,
        group_id=dormant_group.id,
        name="No Points",
        priority=1,
        criteria={"v": 1, "op": "AND", "conditions": [{"metric": "points_balance", "lte": 0}]},
    )
    db_session.add(no_points)
    await db_session.flush()

    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert summary[bronze.id] == {"added": 1, "removed": 0, "member_count": 1}
    assert summary[no_points.id] == {"added": 1, "removed": 0, "member_count": 1}
    memberships = (
        (await db_session.execute(select(UserSegment).where(UserSegment.user_id == test_user.id)))
        .scalars()
        .all()
    )
    assert {m.segment_id for m in memberships} == {bronze.id, no_points.id}


@pytest.mark.asyncio
async def test_or_criteria_matches_on_either_condition(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """An `op: OR` segment matches when only ONE of its two conditions holds:
    txn_count gte 100 (unmet — no activity) OR points_balance lte 0 (met —
    no points account at all)."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="OR Group")
    db_session.add(group)
    await db_session.flush()
    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="Either",
        priority=1,
        criteria={
            "v": 1,
            "op": "OR",
            "conditions": [
                {"metric": "txn_count", "gte": 100},
                {"metric": "points_balance", "lte": 0},
            ],
        },
    )
    db_session.add(segment)
    await db_session.flush()

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert summary[segment.id] == {"added": 1, "removed": 0, "member_count": 1}
    row = (
        await db_session.execute(select(UserSegment).where(UserSegment.segment_id == segment.id))
    ).scalar_one()
    assert row.user_id == test_user.id


@pytest.mark.asyncio
async def test_shared_metric_key_computed_once_across_conditions(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two conditions referencing the SAME (metric, txn_type, window_days) key
    trigger exactly one `compute_metric` call — proves the dedup-by-MetricKey
    behaviour, not just that the end result happens to be correct."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()
    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="Between One And Ten",
        priority=1,
        criteria={
            "v": 1,
            "op": "AND",
            "conditions": [
                {"metric": "txn_count", "gte": 1},
                {"metric": "txn_count", "lte": 10},
            ],
        },
    )
    db_session.add(segment)
    await db_session.flush()
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    calls: list[tuple[str, str | None, int | None]] = []
    original_compute_metric = evaluator.compute_metric
    original_signature = inspect.signature(original_compute_metric)

    async def _spy(*args: Any, **kwargs: Any) -> dict[UUID, Decimal]:
        """Record the (metric, txn_type, window_days) key each call used.

        Binds against `compute_metric`'s real signature rather than assuming
        `metric` is positional index 2 — keeps this spy correct if the
        function's parameter order/shape ever changes.
        """
        bound = original_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        calls.append(
            (
                bound.arguments["metric"],
                bound.arguments.get("txn_type"),
                bound.arguments.get("window_days"),
            )
        )
        return await original_compute_metric(*args, **kwargs)

    monkeypatch.setattr(evaluator, "compute_metric", _spy)

    summary = await recompute_tenant(db_session, test_tenant.id)

    assert calls.count(("txn_count", None, None)) == 1
    assert summary[segment.id] == {"added": 1, "removed": 0, "member_count": 1}


@pytest.mark.asyncio
async def test_windowed_criteria_under_explicit_now_excludes_old_transaction(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """`window_days=30` with an explicit `now=` excludes a transaction from
    100 days before that instant: `txn_count eq 1` only holds if the window
    correctly drops the old transaction (an `eq` bound, not `gte`, so a
    window bug that let the old txn through would flip this to 2 and fail)."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Recent Activity")
    db_session.add(group)
    await db_session.flush()
    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="Recently Active",
        priority=1,
        criteria={
            "v": 1,
            "op": "AND",
            "conditions": [{"metric": "txn_count", "window_days": 30, "eq": 1}],
        },
    )
    db_session.add(segment)
    await db_session.flush()

    frozen_now = datetime.now(UTC)
    counterpart = await _wallet_account(db_session, test_tenant.id, None)
    await _wallet_txn(
        db_session,
        test_tenant.id,
        debit_account=user_wallet,
        credit_account=counterpart,
        days_ago=100,
    )
    await _wallet_txn(
        db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
    )

    summary = await recompute_tenant(db_session, test_tenant.id, now=frozen_now)

    assert summary[segment.id] == {"added": 1, "removed": 0, "member_count": 1}


@pytest.mark.asyncio
async def test_preview_and_recompute_agree_on_lte_zero_widening(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """`preview_criteria` and `recompute_tenant` agree on the absent-user
    universe widening for an `lte`-zero condition (points_balance lte 0)."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Dormant Points")
    db_session.add(group)
    await db_session.flush()
    criteria_dict = {
        "v": 1,
        "op": "AND",
        "conditions": [{"metric": "points_balance", "lte": 0}],
    }
    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="No Points",
        priority=1,
        criteria=criteria_dict,
    )
    db_session.add(segment)
    await db_session.flush()

    frozen_now = datetime.now(UTC)
    summary = await recompute_tenant(db_session, test_tenant.id, now=frozen_now)
    preview_count = await preview_criteria(
        db_session,
        test_tenant.id,
        SegmentCriteria.model_validate(criteria_dict),
        now=frozen_now,
    )

    assert preview_count == 1
    assert summary[segment.id]["member_count"] == preview_count
