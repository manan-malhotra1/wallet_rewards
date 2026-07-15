"""Tests for the customer-facing transaction `reference`.

Every transaction gets a human reference `S_<YYYYMMDDHHMMSS><NNNNNN>` where the
14-digit timestamp is the creation instant (UTC) and NNNNNN a per-tenant running
number drawn from a native Postgres sequence. References are unique WITHIN a
tenant; two tenants number independently. See `.claude/rules/ledger-invariants.md`
and the 0036 migration.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    build_reference,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
)

# `S_` + 14-digit timestamp + at least 6 digits of running number.
_REFERENCE_RE = re.compile(r"^S_\d{14}\d{6,}$")


def _balanced(
    src: Account, dst: Account, amount: Decimal
) -> list[LedgerEntryRequest]:
    """Build a balanced 2-entry pair (debit src, credit dst)."""
    return [
        LedgerEntryRequest(account_id=src.id, entry_type=ENTRY_DEBIT, amount=amount),
        LedgerEntryRequest(account_id=dst.id, entry_type=ENTRY_CREDIT, amount=amount),
    ]


async def _system_pair(session: AsyncSession, tenant: Tenant) -> tuple[Account, Account]:
    """Create two system accounts (no owner) so the balance guard skips them."""
    src = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency="ZAR",
    )
    dst = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="ZAR",
    )
    session.add_all([src, dst])
    await session.commit()
    await session.refresh(src)
    await session.refresh(dst)
    return src, dst


# --- build_reference (pure) --------------------------------------------------


def test_build_reference_format() -> None:
    """`S_` + 14-digit UTC timestamp + zero-padded 6-digit running number."""
    ts = datetime(2026, 7, 15, 14, 30, 22, tzinfo=UTC)
    assert build_reference(ts, 42) == "S_20260715143022000042"


def test_build_reference_matches_pattern() -> None:
    """Any (ts, seq) produces a string matching the documented pattern."""
    ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert _REFERENCE_RE.match(build_reference(ts, 1))


def test_build_reference_keeps_large_numbers() -> None:
    """A running number wider than 6 digits keeps all its digits."""
    ts = datetime(2026, 7, 15, 14, 30, 22, tzinfo=UTC)
    assert build_reference(ts, 1234567) == "S_202607151430221234567"


# --- generation through post_transaction -------------------------------------


@pytest.mark.asyncio
async def test_new_transaction_gets_reference(
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """A transaction posted through the chokepoint carries a valid reference."""
    src, dst = await _system_pair(db_session, test_tenant)
    txn = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="ref-1",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced(src, dst, Decimal("10")),
        ),
    )
    assert txn.reference is not None
    assert _REFERENCE_RE.match(txn.reference), txn.reference


@pytest.mark.asyncio
async def test_reference_number_increments_within_tenant(
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """A second transaction in the same tenant advances the running number."""
    src, dst = await _system_pair(db_session, test_tenant)
    first = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="inc-1",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced(src, dst, Decimal("10")),
        ),
    )
    second = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="inc-2",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced(src, dst, Decimal("10")),
        ),
    )
    assert first.reference is not None and second.reference is not None
    # Last 6+ digits are the running number — the second must be greater.
    first_seq = int(first.reference[16:])
    second_seq = int(second.reference[16:])
    assert second_seq == first_seq + 1


@pytest.mark.asyncio
async def test_two_tenants_number_independently(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Each tenant runs its own sequence — both start at 1."""
    src_a, dst_a = await _system_pair(db_session, test_tenant)
    src_b, dst_b = await _system_pair(db_session, other_tenant)

    txn_a = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="tenant-a-1",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced(src_a, dst_a, Decimal("10")),
        ),
    )
    txn_b = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=other_tenant.id,
            idempotency_key="tenant-b-1",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced(src_b, dst_b, Decimal("10")),
        ),
    )
    assert txn_a.reference is not None and txn_b.reference is not None
    # Both are the FIRST transaction in their own tenant → running number 1.
    assert txn_a.reference.endswith("000001")
    assert txn_b.reference.endswith("000001")


@pytest.mark.asyncio
async def test_idempotent_replay_keeps_reference_and_number(
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Replaying the same key returns the SAME reference — no number burned."""
    src, dst = await _system_pair(db_session, test_tenant)
    request = PostTransactionRequest(
        tenant_id=test_tenant.id,
        idempotency_key="replay-1",
        transaction_type="seed",
        currency="ZAR",
        entries=_balanced(src, dst, Decimal("10")),
    )
    first = await post_transaction(db_session, request)
    replay = await post_transaction(db_session, request)
    assert first.id == replay.id
    assert first.reference == replay.reference

    # A DIFFERENT transaction posted next must be the SECOND number, proving the
    # replay did not consume a sequence value.
    third = await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="replay-2",
            transaction_type="seed",
            currency="ZAR",
            entries=_balanced(src, dst, Decimal("10")),
        ),
    )
    assert first.reference is not None and third.reference is not None
    assert int(third.reference[16:]) == int(first.reference[16:]) + 1


@pytest.mark.asyncio
async def test_reference_unique_within_tenant(
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """No two transactions in a tenant share a reference (unique index)."""
    src, dst = await _system_pair(db_session, test_tenant)
    for i in range(5):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key=f"uniq-{i}",
                transaction_type="seed",
                currency="ZAR",
                entries=_balanced(src, dst, Decimal("10")),
            ),
        )
    from app.shared.models import Transaction

    refs = (
        (
            await db_session.execute(
                select(Transaction.reference).where(Transaction.tenant_id == test_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(refs) == 5
    assert len(set(refs)) == 5
