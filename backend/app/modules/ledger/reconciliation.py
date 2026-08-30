"""Detect and repair drift between cached balances and the ledger.

`account_balance_snapshots` is a derived cache, but `post_transaction`'s
overdraft and `max_balance` guards read it — so a snapshot that disagrees with
`ledger_entries` is a money bug, not a stale-cache annoyance. The ledger stays
the source of truth; this sweep makes that authority effective at runtime rather
than only in CI.

Why this exists: a 50-way load run left 3 of 413 accounts with a cached balance
short by exactly one posting on both legs, all on the points/rewards path. The
mechanism is not yet understood — it did not reproduce in-process at 8-way
concurrency, directly or through the live reward path. Until it is, this sweep is
the containment: drift is found, logged loudly, audited, and corrected, instead
of accumulating silently and forever (nothing in the read path self-heals).

Deliberately NOT on the 60s `rewards.recon_sweep` cadence. Verifying an account
costs one aggregate over its whole history — precisely the O(rows) work the
snapshot exists to keep off the hot path — so running it every minute would
reintroduce the cost it protects. It is a bounded batch on a slow beat instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import structlog
from celery import shared_task
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ledger.snapshots import rebuild_snapshot, sum_from_ledger
from app.shared.models import AccountBalanceSnapshot

log = structlog.get_logger()

# One aggregate per account, so keep the batch small enough that a sweep stays
# well inside the Celery time limit even when several accounts are large.
DEFAULT_BATCH = 200

SOFT_TIME_LIMIT = 540
TIME_LIMIT = 600


@dataclass(frozen=True)
class Drift:
    """One account whose cached balance disagreed with its ledger."""

    account_id: UUID
    cached_balance: Decimal
    ledger_balance: Decimal
    cached_reserved: Decimal
    ledger_reserved: Decimal


async def find_drift(session: AsyncSession, *, batch: int = DEFAULT_BATCH) -> list[Drift]:
    """Re-derive the most recently touched snapshots and report disagreements.

    Ordered by `snapshot_at` descending: a bad writer shows up on accounts that
    are actually moving, so the newest rows are where drift appears first. This
    is a sample, not a proof of global consistency — a full audit is
    `tests/invariants/test_balance_snapshots_match_ledger.py`, or this sweep with
    a batch larger than the account count.

    Args:
        session: Async DB session (read-only).
        batch: Maximum number of accounts to verify this pass.

    Returns:
        The drifted accounts, empty when everything agrees.
    """
    rows = (
        (
            await session.execute(
                select(
                    AccountBalanceSnapshot.account_id,
                    AccountBalanceSnapshot.balance,
                    AccountBalanceSnapshot.reserved_balance,
                )
                .order_by(desc(AccountBalanceSnapshot.snapshot_at))
                .limit(batch)
            )
        )
        .tuples()
        .all()
    )

    drifted: list[Drift] = []
    for account_id, cached_balance, cached_reserved in rows:
        ledger_balance, ledger_reserved = await sum_from_ledger(session, account_id)
        if (
            Decimal(cached_balance or 0) != ledger_balance
            or Decimal(cached_reserved or 0) != ledger_reserved
        ):
            drifted.append(
                Drift(
                    account_id=account_id,
                    cached_balance=Decimal(cached_balance or 0),
                    ledger_balance=ledger_balance,
                    cached_reserved=Decimal(cached_reserved or 0),
                    ledger_reserved=ledger_reserved,
                )
            )
    return drifted


async def repair_drift(session: AsyncSession, drifted: list[Drift]) -> int:
    """Rewrite each drifted snapshot from the ledger, logging what changed.

    Repair is safe in either direction because it writes the absolute derived
    value: the ledger is authoritative, so converging on it can only make a
    balance correct. It does NOT commit — the caller owns the transaction.

    Every repair is logged at error level with both figures. A cache silently
    correcting itself would hide the very bug this sweep exists to surface, so
    the log line is the point as much as the repair is.

    Args:
        session: Async DB session.
        drifted: Accounts reported by `find_drift`.

    Returns:
        How many snapshots were rewritten.
    """
    for d in drifted:
        log.error(
            "balance_snapshot_drift_repaired",
            account_id=str(d.account_id),
            cached_balance=str(d.cached_balance),
            ledger_balance=str(d.ledger_balance),
            balance_delta=str(d.ledger_balance - d.cached_balance),
            cached_reserved=str(d.cached_reserved),
            ledger_reserved=str(d.ledger_reserved),
        )
        await rebuild_snapshot(session, d.account_id)
    return len(drifted)


async def drift_sweep_async(
    session_factory: async_sessionmaker[AsyncSession], *, batch: int = DEFAULT_BATCH
) -> int:
    """Verify a batch of snapshots, repair any drift, commit.

    Args:
        session_factory: Opens one session for the whole sweep.
        batch: Maximum accounts to verify.

    Returns:
        Number of accounts repaired (0 when the cache agrees with the ledger).
    """
    async with session_factory() as session:
        drifted = await find_drift(session, batch=batch)
        if not drifted:
            log.info("balance_snapshot_drift_none", checked=batch)
            return 0
        repaired = await repair_drift(session, drifted)
        await session.commit()
        log.error("balance_snapshot_drift_sweep", checked=batch, repaired=repaired)
        return repaired


# celery's @shared_task is untyped, so under mypy --strict it flags the wrapped
# function as untyped; the ignore is scoped to that one decorator interaction
# (same pattern as rewards/outbox.py's recon_sweep).
@shared_task(  # type: ignore[untyped-decorator]
    name="ledger.snapshot_drift_sweep",
    soft_time_limit=SOFT_TIME_LIMIT,
    time_limit=TIME_LIMIT,
)
def snapshot_drift_sweep() -> int:
    """Celery entrypoint: verify and repair cached balances.

    Each beat run gets a FRESH event loop via `asyncio.run`, so — exactly like
    `rewards.recon_sweep` and `segments.recompute_all` — this builds a dedicated
    NullPool engine per run and disposes it in `finally`, rather than reusing a
    module-level session factory bound to a possibly-closed event loop.

    Returns:
        Number of snapshots repaired this run.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    async def _run() -> int:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            return await drift_sweep_async(factory, batch=settings.SNAPSHOT_DRIFT_BATCH)
        finally:
            await engine.dispose()

    return int(asyncio.run(_run()))
