"""Batch evaluator tests (spec §4) — criteria-driven segment membership recompute.

`_wallet_account` / `_wallet_txn` below mirror the wallet-attributed activity
factories in `tests/segments/test_metrics.py` (duplicated locally rather than
imported, per this repo's test-isolation convention) so `txn_count`-style
criteria conditions see real COMPLETED transactions that touched the user's
own `financial_wallet` account.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    second = await recompute_tenant(db_session, test_tenant.id)
    assert second[bronze.id] == {"added": 0, "removed": 0, "member_count": 1}
    assert second[gold.id] == {"added": 0, "removed": 0, "member_count": 0}

    for _ in range(2):
        await _wallet_txn(
            db_session, test_tenant.id, debit_account=user_wallet, credit_account=counterpart
        )

    third = await recompute_tenant(db_session, test_tenant.id)
    assert third[gold.id] == {"added": 1, "removed": 0, "member_count": 1}
    assert third[bronze.id] == {"added": 0, "removed": 1, "member_count": 0}


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
