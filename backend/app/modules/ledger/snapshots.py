"""Cached per-account balances (`account_balance_snapshots`).

`ledger_entries` remains the source of truth (invariant #1, append-only). This
module keeps a derived cache of `(balance, reserved_balance)` per account so a
balance READ costs one indexed row instead of aggregating the account's whole
history.

Why it matters: a shared account accumulates an entry from every transaction
that touches it — the tenant's `system_fee_collected` takes one from EVERY
transaction, 432k rows/day at 5 TPS — and the aggregate was measured at 931ms
by 5M entries, run while holding the account write lock inside
`post_transaction`. That cost grew forever and never came back down.

Correctness rests on three properties:

1. **One writer per shape.** `ledger_entries` is mutated in exactly three
   places: the INSERT in `post_transaction`, and the two status flips in
   `airtime.service` (`_apply_completed`, `_apply_reversed`). Each calls into
   this module, so no ledger movement bypasses the cache.
2. **Same transaction.** Deltas are applied in the transaction that writes the
   entries, so the cache can never be durably out of step with the ledger.
3. **Deltas, not read-modify-write.** `SET balance = balance + :delta` is
   resolved by Postgres under its own row lock, so two concurrent writers to an
   UNGUARDED account (points, pool and merchant-collection accounts take no
   `FOR UPDATE`) cannot lose an update the way a read-then-write would.

`tests/invariants/test_balance_snapshots_match_ledger.py` re-derives every
snapshot from the ledger after the suite, so a fourth writer added later fails
the build rather than silently corrupting balances.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    AccountBalanceSnapshot,
    LedgerEntry,
)


async def sum_from_ledger(session: AsyncSession, account_id: UUID) -> tuple[Decimal, Decimal]:
    """Derive `(balance, reserved)` for one account straight from the ledger.

    The authoritative computation, and the fallback whenever a snapshot row is
    missing. Cost is O(entries on the account) — this is exactly what the cache
    exists to keep off the hot path, so call it only to build or repair a
    snapshot, never to serve a routine read.

    Args:
        session: Async DB session.
        account_id: The account to aggregate.

    Returns:
        `(balance, reserved)` where balance sums COMPLETED entries (CREDIT
        positive) and reserved sums PENDING entries mirrored (a pending DEBIT
        holds funds, a pending CREDIT releases them).
    """
    # Imported here rather than at module scope: `ledger.service` imports this
    # module from inside `post_transaction`, so a module-level import back into
    # it would close an import cycle.
    from app.modules.ledger.service import signed_balance_expr

    signed = signed_balance_expr()
    result = await session.execute(
        select(
            func.coalesce(func.sum(signed).filter(LedgerEntry.status == ENTRY_STATUS_COMPLETED), 0),
            func.coalesce(func.sum(-signed).filter(LedgerEntry.status == ENTRY_STATUS_PENDING), 0),
        ).where(
            LedgerEntry.account_id == account_id,
            # Keeps the (account_id, status, created_at) index in play and skips
            # REVERSED rows, which contribute to neither figure.
            LedgerEntry.status.in_((ENTRY_STATUS_COMPLETED, ENTRY_STATUS_PENDING)),
        )
    )
    balance_raw, reserved_raw = result.one()
    return Decimal(balance_raw or 0), Decimal(reserved_raw or 0)


async def read_snapshot(session: AsyncSession, account_id: UUID) -> tuple[Decimal, Decimal] | None:
    """Return the cached `(balance, reserved)`, or None when no row exists yet.

    A missing row is not an error — it means this account has never been
    snapshotted (created before the backfill, or never touched). Callers fall
    back to `sum_from_ledger`.
    """
    row = (
        await session.execute(
            select(
                AccountBalanceSnapshot.balance,
                AccountBalanceSnapshot.reserved_balance,
            ).where(AccountBalanceSnapshot.account_id == account_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return Decimal(row[0] or 0), Decimal(row[1] or 0)


async def rebuild_snapshot(session: AsyncSession, account_id: UUID) -> tuple[Decimal, Decimal]:
    """Recompute one account's snapshot from the ledger and store it.

    The repair path: used to seed an account that has no row yet, and by the
    backfill. Writes the absolute derived value rather than a delta, so it is
    safe to run at any time and converges a drifted row.

    Returns:
        The `(balance, reserved)` that was written.
    """
    balance, reserved = await sum_from_ledger(session, account_id)
    # RETURNING tells us whether a row existed without reaching for the
    # untyped `rowcount` attribute on Result.
    updated = (
        await session.execute(
            update(AccountBalanceSnapshot)
            .where(AccountBalanceSnapshot.account_id == account_id)
            .values(balance=balance, reserved_balance=reserved, snapshot_at=func.now())
            .returning(AccountBalanceSnapshot.account_id)
        )
    ).scalar_one_or_none()
    if updated is None:
        # ON CONFLICT rather than a plain INSERT: `account_id` is UNIQUE, and two
        # concurrent READS of an account that has no row yet would otherwise
        # collide and turn a balance GET into a 500. Whoever loses the race just
        # re-writes the same derived value.
        await session.execute(
            pg_insert(AccountBalanceSnapshot)
            .values(account_id=account_id, balance=balance, reserved_balance=reserved)
            .on_conflict_do_update(
                index_elements=[AccountBalanceSnapshot.account_id],
                set_={
                    "balance": balance,
                    "reserved_balance": reserved,
                    "snapshot_at": func.now(),
                },
            )
        )
    return balance, reserved


async def apply_deltas(session: AsyncSession, deltas: dict[UUID, tuple[Decimal, Decimal]]) -> None:
    """Fold per-account `(balance_delta, reserved_delta)` into the cache.

    Must be called in the SAME transaction as the ledger write that produced the
    deltas, and AFTER those rows are flushed — the INSERT branch derives the
    absolute value from the ledger, which only lands correctly if the new entries
    are already visible.

    Each account is one statement. The conflict branch applies the DELTA to
    whatever is already stored rather than writing a value computed earlier:
    a value read before the statement blocks is stale by the time the block
    clears, and writing it back silently discards the winner's update. That is
    exactly how a concurrent pair of credits both passed a `max_balance` check
    that should have rejected one of them (the M-01 race, invariant #11).

    Args:
        session: Async DB session, inside the ledger write's transaction.
        deltas: account_id -> (balance_delta, reserved_delta). Zero-zero entries
            are skipped.

    Side effects:
        Updates or creates one `account_balance_snapshots` row per account.
    """
    for account_id, (balance_delta, reserved_delta) in deltas.items():
        if not balance_delta and not reserved_delta:
            continue
        # Fast path: the row exists (every account has one after the 0071
        # backfill), so this is a single indexed UPDATE and no aggregate runs.
        moved = (
            await session.execute(
                update(AccountBalanceSnapshot)
                .where(AccountBalanceSnapshot.account_id == account_id)
                .values(
                    balance=AccountBalanceSnapshot.balance + balance_delta,
                    reserved_balance=AccountBalanceSnapshot.reserved_balance + reserved_delta,
                    snapshot_at=func.now(),
                )
                .returning(AccountBalanceSnapshot.account_id)
            )
        ).scalar_one_or_none()
        if moved is not None:
            continue

        # Row absent (an account created before the backfill). Seed it from the
        # ledger — correct because the caller flushed this transaction's entries
        # first, so the derived value already includes them.
        seed_balance, seed_reserved = await sum_from_ledger(session, account_id)
        await session.execute(
            pg_insert(AccountBalanceSnapshot)
            .values(
                account_id=account_id,
                balance=seed_balance,
                reserved_balance=seed_reserved,
            )
            .on_conflict_do_update(
                index_elements=[AccountBalanceSnapshot.account_id],
                set_={
                    # If a concurrent writer created the row first, apply our
                    # DELTA to theirs rather than overwriting with the value we
                    # computed before blocking — that value is stale by the time
                    # the block clears, and writing it back discards their
                    # update. Losing that update is how two credits both passed a
                    # max_balance check that should have rejected one (the M-01
                    # race, invariant #11). Delta-on-conflict is order-independent:
                    # whoever lands second adds to whatever is already there.
                    "balance": AccountBalanceSnapshot.balance + balance_delta,
                    "reserved_balance": (AccountBalanceSnapshot.reserved_balance + reserved_delta),
                    "snapshot_at": func.now(),
                },
            )
        )


def entry_deltas(
    entries: list[tuple[UUID, Decimal]], *, status: str
) -> dict[UUID, tuple[Decimal, Decimal]]:
    """Turn signed per-entry amounts into per-account snapshot deltas.

    Args:
        entries: `(account_id, signed_amount)` pairs, where signed_amount is
            positive for a CREDIT and negative for a DEBIT.
        status: the status those entries carry — COMPLETED entries move
            `balance`, PENDING entries move `reserved` (mirrored).

    Returns:
        account_id -> (balance_delta, reserved_delta).
    """
    deltas: dict[UUID, tuple[Decimal, Decimal]] = {}
    for account_id, signed in entries:
        balance_delta, reserved_delta = deltas.get(account_id, (Decimal(0), Decimal(0)))
        if status == ENTRY_STATUS_COMPLETED:
            balance_delta += signed
        elif status == ENTRY_STATUS_PENDING:
            # A pending DEBIT (negative signed) raises the amount held.
            reserved_delta -= signed
        deltas[account_id] = (balance_delta, reserved_delta)
    return deltas


async def deltas_for_status_flip(
    session: AsyncSession, transaction_id: UUID, *, to_status: str
) -> dict[UUID, tuple[Decimal, Decimal]]:
    """Deltas for flipping one transaction's PENDING entries to `to_status`.

    Airtime reserves funds with PENDING entries and later settles them: PENDING
    -> COMPLETED on a successful vend, PENDING -> REVERSED on a refund. Both move
    money without inserting a row, so both must move the cache too.

    Call this BEFORE running the UPDATE — it reads the rows while they are still
    PENDING. A double-finalise finds nothing pending and yields no deltas, which
    matches the UPDATE's own `status == PENDING` guard.

    Args:
        session: Async DB session.
        transaction_id: The parent transaction whose entries are being settled.
        to_status: `ENTRY_STATUS_COMPLETED` or `ENTRY_STATUS_REVERSED`.

    Returns:
        account_id -> (balance_delta, reserved_delta).
    """
    from app.modules.ledger.service import signed_balance_expr

    rows = (
        await session.execute(
            select(LedgerEntry.account_id, func.coalesce(func.sum(signed_balance_expr()), 0))
            .where(
                LedgerEntry.transaction_id == transaction_id,
                LedgerEntry.status == ENTRY_STATUS_PENDING,
            )
            .group_by(LedgerEntry.account_id)
        )
    ).all()

    deltas: dict[UUID, tuple[Decimal, Decimal]] = {}
    for account_id, total_raw in rows:
        total = Decimal(total_raw or 0)
        # Leaving PENDING always releases the hold: reserved held -total, so
        # dropping it moves reserved by +total.
        # Settling additionally realises the money; reversing does not.
        balance_delta = total if to_status == ENTRY_STATUS_COMPLETED else Decimal(0)
        deltas[account_id] = (balance_delta, total)
    return deltas
