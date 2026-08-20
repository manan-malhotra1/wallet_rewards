"""Create the internal-redemption system wallets for existing rewards tenants.

Why a script and not a migration: this creates ledger accounts. Account
creation should be a deliberate, reviewable act with a printed before/after,
not a side effect of `alembic upgrade head` on an unattended deploy.

Context: Module 11b (Pay-PRD-1230/1240) added two system accounts —
`cashback_provider_wallet` (per fiat currency; funds internal-redemption
payouts AND cashback rewards) and `points_redemption_wallet` (PTS; the burn
sink). New tenants get them from `_provision_system_wallets`, but tenants
created before that change have neither. The cashback wallet especially must
exist BEFORE it can be treasury-funded, so without this backfill an operator
cannot pre-fund it and every payout 409s `insufficient_cashback_funds`.

Scope: only tenants whose business_type includes rewards (`rewards` / `both`)
— a wallet-only tenant has no points surface (B6.1). The cashback wallet is
created for every currency the tenant already holds a `system_cash_inflow` in
(that set IS the tenant's live fiat currency list), plus its base currency.

Usage:
    python scripts/backfill_redemption_wallets.py            # dry run, prints a plan
    python scripts/backfill_redemption_wallets.py --apply    # writes

Idempotent: an existing (tenant, type, currency) account is left alone, so
re-running is safe.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.shared.models import (  # noqa: E402
    ACCOUNT_TYPE_CASHBACK_PROVIDER,
    ACCOUNT_TYPE_POINTS_REDEMPTION,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
)

_REWARDS_MODES = ("rewards", "both")


async def _existing_types(session: AsyncSession, tenant_id: object) -> set[tuple[str, str]]:
    """Return the tenant's existing system (account_type, currency) pairs."""
    rows = (
        await session.execute(
            select(Account.account_type, Account.currency).where(
                Account.tenant_id == tenant_id, Account.user_id.is_(None)
            )
        )
    ).all()
    return {(t, c) for t, c in rows}


async def _fiat_currencies(session: AsyncSession, tenant: Tenant) -> set[str]:
    """The tenant's live fiat currencies: every cash-float currency + base."""
    rows = (
        (
            await session.execute(
                select(Account.currency).where(
                    Account.tenant_id == tenant.id,
                    Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
                    Account.user_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return {c.upper() for c in rows} | {tenant.base_currency.strip().upper()}


async def main(apply: bool) -> None:
    """Print (and optionally write) the missing redemption wallets."""
    created = 0
    async with SessionLocal() as session:
        tenants = (
            (await session.execute(select(Tenant).where(Tenant.business_type.in_(_REWARDS_MODES))))
            .scalars()
            .all()
        )
        print(f"{len(tenants)} rewards-enabled tenant(s)\n")

        for tenant in tenants:
            existing = await _existing_types(session, tenant.id)
            wanted: list[tuple[str, str]] = [(ACCOUNT_TYPE_POINTS_REDEMPTION, "PTS")]
            for currency in sorted(await _fiat_currencies(session, tenant)):
                wanted.append((ACCOUNT_TYPE_CASHBACK_PROVIDER, currency))

            missing = [pair for pair in wanted if pair not in existing]
            if not missing:
                print(f"  {tenant.name}: nothing to do")
                continue
            print(f"  {tenant.name}:")
            for account_type, currency in missing:
                print(f"    + {account_type} ({currency})")
                if apply:
                    session.add(
                        Account(
                            tenant_id=tenant.id,
                            account_type=account_type,
                            currency=currency,
                        )
                    )
                    created += 1

        if apply:
            await session.commit()
            print(f"\nCreated {created} account(s).")
        else:
            print("\nDry run — re-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
