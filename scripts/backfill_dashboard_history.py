#!/usr/bin/env python3
"""Backfill historical transactions + registrations so the dashboard can compare periods.

The analytics endpoints compare a window against the equal-length window before it
(`resolve_window`: current = [now-span, now), previous = [now-2*span, now-span)). With
only a few days of real data every "vs prev" figure is meaningless, so month-on-month
and week-on-week read as flat or blank. This script lays down a trending daily history
across `--days` (default 60 — enough that BOTH halves of a 30d comparison are populated).

Everything written is a *legitimate* transaction, not a display-only row, because the
dashboard derives its numbers from real tables:

  * `transactions` (status COMPLETED, per-currency amount / fee_amount / tax_amount)
    feeds Transactions, Volume, Revenue, Service mix and Transaction status.
  * `ledger_entries` on `financial_wallet` accounts feeds Net flow and liquidity.
  * `users.created_at` feeds New users.

So each generated transaction gets a matching, balanced double-entry set: total DEBITs
equal total CREDITs, entry-for-entry, with `created_at` on both the transaction and its
entries set to the historical timestamp. The ledger stays append-only (inserts only) and
`SUM(ledger_entries)` still nets to zero afterwards — verified at the end of the run.

Ledger shape per generated type (mirrors what the real services post):

  fund             DEBIT float            -> CREDIT consumer          (no charges)
  cash_in          DEBIT agent            -> CREDIT consumer + fee + tax
  p2p              DEBIT consumer         -> CREDIT consumer + fee + tax
  cashout          DEBIT consumer         -> CREDIT agent    + fee + tax
  merchant_cashin  DEBIT merchant         -> CREDIT consumer + fee + tax

`commission_amount` is left at 0: commission is funded from a pool account and would
need a fifth leg per transaction to stay balanced, while contributing nothing to any
dashboard figure (revenue is the fee only — see `revenue_by_service`).

Every row is tagged with an `idempotency_key` prefixed `backfill-` so this data is
identifiable and removable later; `--undo` deletes exactly those rows and nothing else.

Actors are drawn from existing users — the script never invents balances. Payer wallets
are debited for real, so amounts are kept small (`--min-amount`/`--max-amount`) and
spread across the whole pool; the run refuses to start if any payer pool is empty and
reports any wallet it would drive negative.

Usage (from the repo root — needs backend/.env on the path, hence the cd):
    cd backend && ../backend/.venv/bin/python ../scripts/backfill_dashboard_history.py
    ... --days 60 --dry-run          # report the plan, write nothing
    ... --undo                       # remove previously backfilled rows
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import case, delete, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.shared.models import (  # noqa: E402
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    TXN_STATUS_COMPLETED,
    Account,
    AuthAttempt,
    LedgerEntry,
    Referral,
    ReferralCode,
    RewardEvent,
    Tenant,
    Transaction,
    User,
    UserIdentifier,
    UserProfile,
    UserRole,
    UserRuleProgress,
    UserSegment,
)

BACKFILL_PREFIX = "backfill-"

# Service mix. Weights are relative; `fund` is the inflow that keeps consumer
# wallets solvent across the history, the rest circulate or extract.
SERVICE_MIX = (
    ("p2p", 34),
    ("cash_in", 28),
    ("cashout", 14),
    ("fund", 16),
    ("merchant_cashin", 8),
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--tenant-name", default="Sasai-ZA")
    p.add_argument("--currency", default="ZAR")
    p.add_argument(
        "--days", type=int, default=60, help="Days of history to lay down, ending yesterday."
    )
    p.add_argument(
        "--txns-start",
        type=int,
        default=55,
        help="Approx transactions on the oldest day (grows to --txns-end).",
    )
    p.add_argument(
        "--txns-end", type=int, default=165, help="Approx transactions on the most recent day."
    )
    p.add_argument(
        "--users-start", type=int, default=12, help="Approx registrations on the oldest day."
    )
    p.add_argument(
        "--users-end", type=int, default=48, help="Approx registrations on the most recent day."
    )
    p.add_argument("--min-amount", type=int, default=20)
    p.add_argument("--max-amount", type=int, default=200)
    p.add_argument(
        "--user-phone-prefix",
        default="+2788",
        help="Identifier block for generated registrations (must be unused). "
        "Stored already-normalised (no spaces) because a direct ORM "
        "insert bypasses the app's identifier normalisation.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=20260820,
        help="RNG seed — same seed reproduces the same history.",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Print the plan and totals; write nothing."
    )
    p.add_argument(
        "--undo",
        action="store_true",
        help="Delete rows previously written by this script, then exit.",
    )
    p.add_argument(
        "--txns-only",
        action="store_true",
        help="Generate transactions but no registrations — for topping up "
        "volume on top of an existing backfill.",
    )
    p.add_argument(
        "--allow-existing",
        action="store_true",
        help="Proceed even though backfilled rows already exist (use with "
        "--txns-only to add volume rather than double-count a rerun).",
    )
    p.add_argument(
        "--fix-negatives",
        action="store_true",
        help="Give every negative financial_wallet a backdated opening "
        "balance from the float, then exit. Run after a backfill that "
        "debited an actor which started at zero.",
    )
    return p.parse_args()


@dataclass
class Pools:
    """Wallet pools the generator draws actors from.

    Each entry is (user_id, account_id) — the transaction needs the user, the
    ledger entry needs the account.
    """

    consumers: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    agents: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    merchants: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    float_account: uuid.UUID | None = None
    fee_account: uuid.UUID | None = None
    tax_account: uuid.UUID | None = None


async def load_pools(session: AsyncSession, tenant_id: uuid.UUID, currency: str) -> Pools:
    """Collect the wallet + system accounts the generated history posts against.

    Raises:
        SystemExit: a required pool or system account is missing, which would
            otherwise surface as an unbalanced ledger halfway through the run.
    """
    pools = Pools()
    stmt = (
        select(User.user_type, User.id, Account.id)
        .join(Account, Account.user_id == User.id)
        .where(
            User.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.currency == currency,
        )
    )
    for user_type, user_id, account_id in (await session.execute(stmt)).all():
        if user_type == "consumer":
            pools.consumers.append((user_id, account_id))
        elif user_type in ("agent", "super_agent"):
            pools.agents.append((user_id, account_id))
        elif user_type in ("merchant", "head_merchant"):
            pools.merchants.append((user_id, account_id))

    sys_stmt = select(Account.account_type, Account.id).where(
        Account.tenant_id == tenant_id,
        Account.user_id.is_(None),
        Account.currency == currency,
    )
    for account_type, account_id in (await session.execute(sys_stmt)).all():
        if account_type == "system_cash_inflow":
            pools.float_account = account_id
        elif account_type == "system_fee_collected":
            pools.fee_account = account_id
        elif account_type == "tax_service_collected":
            pools.tax_account = account_id

    missing = [
        name
        for name, val in (
            ("consumer wallets", pools.consumers),
            ("agent wallets", pools.agents),
            ("merchant wallets", pools.merchants),
            ("system_cash_inflow", pools.float_account),
            ("system_fee_collected", pools.fee_account),
            ("tax_service_collected", pools.tax_account),
        )
        if not val
    ]
    if missing:
        sys.exit(f"cannot backfill — missing: {', '.join(missing)}. Run scripts/seed.py first.")
    return pools


def money(value: Decimal) -> Decimal:
    """Round to 2dp the way the pricing engine does (half-up, not banker's)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def charges_for(amount: Decimal, service: str) -> tuple[Decimal, Decimal]:
    """Fee + tax for one generated transaction.

    Mirrors the shape of the live slab pricing (a small flat-ish fee with tax
    charged on the fee) rather than inventing a percentage of principal, so
    Revenue-by-service reads plausibly. `fund` is free, as it is in production.
    """
    if service == "fund":
        return Decimal(0), Decimal(0)
    fee = money(max(Decimal("2.00"), amount * Decimal("0.02")))
    tax = money(fee * Decimal("0.0352"))
    return fee, tax


def pick_legs(
    service: str, pools: Pools, rng: random.Random
) -> tuple[tuple[uuid.UUID | None, uuid.UUID], tuple[uuid.UUID, uuid.UUID]]:
    """Choose (payer_user, payer_account) and (payee_user, payee_account) for a service.

    Returns payer_user as None for `fund`, whose debit side is the operator float
    and therefore has no initiating end user.
    """
    consumer = rng.choice(pools.consumers)
    if service == "fund":
        assert pools.float_account is not None
        return (None, pools.float_account), consumer
    if service == "cash_in":
        return pools.agents[rng.randrange(len(pools.agents))], consumer
    if service == "merchant_cashin":
        return pools.merchants[rng.randrange(len(pools.merchants))], consumer
    if service == "cashout":
        return consumer, pools.agents[rng.randrange(len(pools.agents))]
    # p2p — two distinct consumers.
    other = rng.choice(pools.consumers)
    while other[0] == consumer[0] and len(pools.consumers) > 1:
        other = rng.choice(pools.consumers)
    return consumer, other


def daily_count(
    day_index: int, total_days: int, start: int, end: int, when: datetime, rng: random.Random
) -> int:
    """Transactions (or registrations) for one day: linear growth + weekly seasonality.

    A flat random count makes week-on-week comparisons read as noise, so the series
    trends upward across the window and dips at weekends — that is what makes a
    period-over-period delta meaningful rather than arbitrary.
    """
    progress = day_index / max(total_days - 1, 1)
    base = start + (end - start) * progress
    weekend = 0.62 if when.weekday() >= 5 else 1.0
    return max(1, int(base * weekend * rng.uniform(0.85, 1.15)))


def build_day(
    when_day: datetime,
    n_txns: int,
    tenant_id: uuid.UUID,
    currency: str,
    pools: Pools,
    args: argparse.Namespace,
    rng: random.Random,
) -> tuple[list[dict], list[dict], Decimal, Decimal]:
    """Generate one day's transaction + ledger-entry rows.

    Returns:
        (transaction_mappings, ledger_mappings, volume, fee_total) — mappings are
        plain dicts for a bulk ORM insert; 24k individual objects per run is
        needlessly slow otherwise.
    """
    services, weights = zip(*SERVICE_MIX, strict=True)
    txn_rows: list[dict] = []
    entry_rows: list[dict] = []
    volume = Decimal(0)
    fees = Decimal(0)

    for _ in range(n_txns):
        service = rng.choices(services, weights=weights, k=1)[0]
        amount = money(Decimal(str(rng.randint(args.min_amount, args.max_amount))))
        fee, tax = charges_for(amount, service)
        (payer_user, payer_account), (_payee_user, payee_account) = pick_legs(service, pools, rng)
        # Spread across the working day so `day` buckets look organic and an
        # `hour` granularity view is not a single spike.
        stamp = when_day + timedelta(
            hours=rng.randint(6, 21), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
        )
        txn_id = uuid.uuid4()
        txn_rows.append(
            {
                "id": txn_id,
                "tenant_id": tenant_id,
                "idempotency_key": f"{BACKFILL_PREFIX}{txn_id.hex}",
                "transaction_type": service,
                "base_transaction_type": service,
                "status": TXN_STATUS_COMPLETED,
                "initiated_by": payer_user,
                "amount": amount,
                "fee_amount": fee,
                "tax_amount": tax,
                "commission_amount": Decimal(0),
                "currency": currency,
                "retry_count": 0,
                "created_at": stamp,
                "updated_at": stamp,
            }
        )

        def entry(
            account_id: uuid.UUID,
            entry_type: str,
            value: Decimal,
            _txn_id: uuid.UUID = txn_id,
            _stamp: datetime = stamp,
        ) -> dict:
            """One ledger leg. txn_id/stamp are bound as defaults, not closed over,
            so the row can never pick up a later iteration's values."""
            return {
                "id": uuid.uuid4(),
                "transaction_id": _txn_id,
                "account_id": account_id,
                "entry_type": entry_type,
                "amount": value,
                "currency": currency,
                "status": ENTRY_STATUS_COMPLETED,
                "created_at": _stamp,
            }

        # Payer bears principal + charges; payee receives principal; charges land
        # in their collection accounts. Debits and credits match exactly.
        entry_rows.append(entry(payer_account, ENTRY_DEBIT, amount + fee + tax))
        entry_rows.append(entry(payee_account, ENTRY_CREDIT, amount))
        if fee > 0:
            assert pools.fee_account is not None
            entry_rows.append(entry(pools.fee_account, ENTRY_CREDIT, fee))
        if tax > 0:
            assert pools.tax_account is not None
            entry_rows.append(entry(pools.tax_account, ENTRY_CREDIT, tax))

        volume += amount
        fees += fee
    return txn_rows, entry_rows, volume, fees


def build_users(
    when_day: datetime,
    n_users: int,
    tenant_id: uuid.UUID,
    args: argparse.Namespace,
    start_seq: int,
    rng: random.Random,
) -> tuple[list[dict], list[dict]]:
    """Generate one day's registrations (user + phone identifier), backdated.

    New-user counts come straight from `users.created_at`, so a user row with a
    unique identifier is all a registration needs — no wallet is implied.
    """
    users: list[dict] = []
    idents: list[dict] = []
    for i in range(n_users):
        seq = start_seq + i
        user_id = uuid.uuid4()
        stamp = when_day + timedelta(
            hours=rng.randint(6, 22), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
        )
        users.append(
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "user_type": "consumer",
                "status": "active",
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
        idents.append(
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "tenant_id": tenant_id,
                "identifier_type": "phone",
                "identifier_value": f"{args.user_phone_prefix}{seq:07d}",
                "verified": True,
                "created_at": stamp,
            }
        )
    return users, idents


async def undo(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    prefix: str,
    phone_prefix: str,
) -> None:
    """Delete only rows this script created, identified by the idempotency prefix."""
    txn_ids = (
        (
            await session.execute(
                select(Transaction.id).where(
                    Transaction.tenant_id == tenant_id,
                    Transaction.idempotency_key.like(f"{prefix}%"),
                )
            )
        )
        .scalars()
        .all()
    )
    # Generated users are identified by their dedicated identifier block: `User`
    # itself carries no name columns to tag (the profile is a separate table).
    user_ids = (
        (
            await session.execute(
                select(UserIdentifier.user_id).where(
                    UserIdentifier.tenant_id == tenant_id,
                    UserIdentifier.identifier_value.like(f"{phone_prefix}%"),
                )
            )
        )
        .scalars()
        .all()
    )
    if txn_ids:
        await session.execute(delete(LedgerEntry).where(LedgerEntry.transaction_id.in_(txn_ids)))
        await session.execute(delete(Transaction).where(Transaction.id.in_(txn_ids)))
    if user_ids:
        # Order matters: every table that references users.id must be cleared
        # first. Dynamic segments in particular WILL have claimed these users, so
        # deleting the user row directly fails on the user_segments FK.
        for model, column in (
            (UserSegment, UserSegment.user_id),
            (UserRuleProgress, UserRuleProgress.user_id),
            (RewardEvent, RewardEvent.user_id),
            (UserRole, UserRole.user_id),
            (UserProfile, UserProfile.user_id),
            (AuthAttempt, AuthAttempt.user_id),
            (ReferralCode, ReferralCode.user_id),
            (UserIdentifier, UserIdentifier.user_id),
        ):
            await session.execute(delete(model).where(column.in_(user_ids)))
        await session.execute(delete(Referral).where(Referral.referred_user_id.in_(user_ids)))
        await session.execute(delete(Referral).where(Referral.referrer_user_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.commit()
    print(f"removed {len(txn_ids)} backfilled transactions and {len(user_ids)} users")


async def fix_negatives(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    currency: str,
    days: int,
) -> None:
    """Fund any negative user wallet from the float, backdated before the history.

    The generator picks payers uniformly from each pool, but a pool can contain an
    actor that never held money (an unfunded agent, the super_agent, a head_merchant
    that only exists as a parent). Debiting one of those drives it negative, which is
    a state the live guard would never allow — `post_transaction` floors every user
    wallet on debit.

    The honest repair is an opening balance: a real actor transacting from day one
    would have been funded first. So this posts a `fund` (DEBIT float / CREDIT wallet)
    dated one day BEFORE the generated window starts, sized to clear the shortfall
    with a small buffer, leaving the wallet non-negative at every later point.
    """
    signed = func.sum(
        case(
            (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount), else_=-LedgerEntry.amount
        )
    )
    rows = (
        await session.execute(
            select(Account.id, signed.label("balance"))
            .join(LedgerEntry, LedgerEntry.account_id == Account.id)
            .where(
                Account.tenant_id == tenant_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == currency,
                LedgerEntry.status == ENTRY_STATUS_COMPLETED,
            )
            .group_by(Account.id)
            .having(signed < 0)
        )
    ).all()
    if not rows:
        print("no negative wallets — nothing to fix")
        return

    float_account = (
        await session.execute(
            select(Account.id).where(
                Account.tenant_id == tenant_id,
                Account.user_id.is_(None),
                Account.currency == currency,
                Account.account_type == "system_cash_inflow",
            )
        )
    ).scalar_one()

    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    stamp = today - timedelta(days=days + 1) + timedelta(hours=5)
    txn_rows: list[dict] = []
    entry_rows: list[dict] = []
    for account_id, balance in rows:
        # Clear the shortfall and leave headroom so rounding can't re-cross zero.
        topup = money(abs(Decimal(balance)) * Decimal("1.10") + Decimal(100))
        txn_id = uuid.uuid4()
        txn_rows.append(
            {
                "id": txn_id,
                "tenant_id": tenant_id,
                "idempotency_key": f"{BACKFILL_PREFIX}open-{txn_id.hex}",
                "transaction_type": "fund",
                "base_transaction_type": "fund",
                "status": TXN_STATUS_COMPLETED,
                "initiated_by": None,
                "amount": topup,
                "fee_amount": Decimal(0),
                "tax_amount": Decimal(0),
                "commission_amount": Decimal(0),
                "currency": currency,
                "retry_count": 0,
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
        for account, entry_type in ((float_account, ENTRY_DEBIT), (account_id, ENTRY_CREDIT)):
            entry_rows.append(
                {
                    "id": uuid.uuid4(),
                    "transaction_id": txn_id,
                    "account_id": account,
                    "entry_type": entry_type,
                    "amount": topup,
                    "currency": currency,
                    "status": ENTRY_STATUS_COMPLETED,
                    "created_at": stamp,
                }
            )
        print(
            f"  opening balance {currency} {topup} -> wallet {account_id} "
            f"(was {Decimal(balance):.2f})"
        )

    await session.run_sync(
        lambda sess, t=txn_rows, e=entry_rows: (
            sess.bulk_insert_mappings(Transaction, t),
            sess.bulk_insert_mappings(LedgerEntry, e),
        )
    )
    await session.commit()
    print(f"funded {len(rows)} wallet(s), backdated to {stamp:%Y-%m-%d}")


async def verify(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Assert the ledger still balances and no user wallet was driven negative.

    Checks the two invariants this script could plausibly break — per-transaction
    double-entry equality and the global sum-to-zero — plus the one balance risk
    inherent in debiting real wallets historically.
    """
    # Per-transaction debit/credit equality, expressed with two conditional sums.
    debit = func.sum(case((LedgerEntry.entry_type == ENTRY_DEBIT, LedgerEntry.amount), else_=0))
    credit = func.sum(case((LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount), else_=0))
    grouped = (
        select(LedgerEntry.transaction_id)
        .where(LedgerEntry.status == ENTRY_STATUS_COMPLETED)
        .group_by(LedgerEntry.transaction_id)
        .having(debit != credit)
        .subquery()
    )
    unbalanced = (await session.execute(select(func.count()).select_from(grouped))).scalar_one()

    signed = func.sum(
        case(
            (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount), else_=-LedgerEntry.amount
        )
    )
    net = (
        await session.execute(select(signed).where(LedgerEntry.status == ENTRY_STATUS_COMPLETED))
    ).scalar_one()

    negatives = (
        await session.execute(
            select(func.count()).select_from(
                select(Account.id)
                .join(LedgerEntry, LedgerEntry.account_id == Account.id)
                .where(
                    Account.tenant_id == tenant_id,
                    Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                    LedgerEntry.status == ENTRY_STATUS_COMPLETED,
                )
                .group_by(Account.id)
                .having(signed < 0)
                .subquery()
            )
        )
    ).scalar_one()

    print("\n-- verification --")
    print(f"  unbalanced transactions : {unbalanced}   (must be 0)")
    print(f"  global signed ledger sum: {net}   (must be 0)")
    print(f"  negative user wallets   : {negatives}   (must be 0)")


async def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    async with SessionLocal() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.name == args.tenant_name))
        ).scalar_one_or_none()
        if tenant is None:
            sys.exit(f"tenant {args.tenant_name!r} not found — run scripts/seed.py")
        tenant_id = tenant.id

        if args.undo:
            await undo(session, tenant_id, BACKFILL_PREFIX, args.user_phone_prefix)
            return

        if args.fix_negatives:
            await fix_negatives(session, tenant_id, args.currency, args.days)
            await verify(session, tenant_id)
            return

        existing = (
            await session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.tenant_id == tenant_id,
                    Transaction.idempotency_key.like(f"{BACKFILL_PREFIX}%"),
                )
            )
        ).scalar_one()
        if existing and not args.allow_existing:
            sys.exit(
                f"{existing} backfilled transactions already exist. Re-run with --undo "
                f"first if you want to regenerate (avoids double-counting)."
            )

        pools = await load_pools(session, tenant_id, args.currency)
        print(f"tenant {args.tenant_name} = {tenant_id}")
        print(
            f"pools: {len(pools.consumers)} consumer / {len(pools.agents)} agent / "
            f"{len(pools.merchants)} merchant wallets"
        )

        # Whole days, oldest first, ending yesterday so today's live data is untouched.
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        days = [today - timedelta(days=args.days - i) for i in range(args.days)]

        seq = 1
        total_txns = total_users = 0
        total_volume = total_fees = Decimal(0)

        for idx, day in enumerate(days):
            n_txns = daily_count(idx, args.days, args.txns_start, args.txns_end, day, rng)
            n_users = daily_count(idx, args.days, args.users_start, args.users_end, day, rng)
            txn_rows, entry_rows, volume, fees = build_day(
                day, n_txns, tenant_id, args.currency, pools, args, rng
            )
            if args.txns_only:
                n_users, user_rows, ident_rows = 0, [], []
            else:
                user_rows, ident_rows = build_users(day, n_users, tenant_id, args, seq, rng)
                seq += n_users

            if not args.dry_run:
                await session.run_sync(
                    lambda s, t=txn_rows, e=entry_rows, u=user_rows, i=ident_rows: (
                        s.bulk_insert_mappings(User, u),
                        s.bulk_insert_mappings(UserIdentifier, i),
                        s.bulk_insert_mappings(Transaction, t),
                        s.bulk_insert_mappings(LedgerEntry, e),
                    )
                )
                await session.commit()  # per-day commit keeps progress durable

            total_txns += n_txns
            total_users += n_users
            total_volume += volume
            total_fees += fees
            if idx % 10 == 0 or idx == args.days - 1:
                print(
                    f"  {day:%Y-%m-%d}  txns={n_txns:>4}  users={n_users:>3}  "
                    f"(cumulative {total_txns} txns / {total_users} users)",
                    flush=True,
                )

        verb = "would write" if args.dry_run else "wrote"
        print(f"\n{verb}: {total_txns} transactions, {total_users} registrations")
        print(
            f"  volume {args.currency} {total_volume:,.2f} · fees {args.currency} "
            f"{total_fees:,.2f} over {args.days} days"
        )
        if args.dry_run:
            print("dry run — nothing written")
            return
        await verify(session, tenant_id)


if __name__ == "__main__":
    asyncio.run(main())
