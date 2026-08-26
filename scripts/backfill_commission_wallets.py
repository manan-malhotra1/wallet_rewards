"""Retrofit commission wallets onto an existing tenant's users.

Why a script and not a migration: this creates ledger accounts, which should be
a deliberate, reviewable act with a printed before/after — not a side effect of
`alembic upgrade head` on an unattended deploy. Same reasoning as
`backfill_redemption_wallets.py`.

Context: `tenants.commission_wallet_enabled` is CREATION-TIME ONLY (spec
2026-08-26, D3). That immutability is what removes backfill-on-flip, teardown
of non-zero balances and any `backfill_pending` intermediate state — but it
also means a tenant created before the commission-wallet edition can never
adopt the feature through the product. This script is the sanctioned retrofit:
an operator sets the column deliberately, then runs this.

Scope: every user in the named tenant whose `user_type` resolves to the Retail
or Business category, for every active FINANCIAL instrument. Consumers get
nothing; points instruments provision nothing.

Usage:
    python scripts/backfill_commission_wallets.py <tenant_id>            # dry run
    python scripts/backfill_commission_wallets.py <tenant_id> --apply    # writes

Idempotent: an existing (user, type, currency) account is left alone, so
re-running is safe.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.modules.accounts.provisioning import (  # noqa: E402
    active_financial_currencies,
    provision_user_accounts,
    wanted_account_types,
)
from app.shared.models import ACCOUNT_TYPE_COMMISSION_WALLET, Tenant, User  # noqa: E402


async def backfill_tenant(
    session: AsyncSession, tenant_id: UUID, *, apply: bool = True
) -> int:
    """Provision every eligible user in one tenant.

    Args:
        session: Async DB session. NOT committed here — the caller commits, so
            a dry run can roll back cleanly.
        tenant_id: The tenant to retrofit.
        apply: When False, count what WOULD be created without adding rows.

    Returns:
        Number of account rows created (or that would be, on a dry run).

    Raises:
        ValueError: the tenant does not exist, or its `commission_wallet_enabled`
            flag is off. The script PROVISIONS wallets; it deliberately does not
            enable the feature, so switching it on stays an explicit act with
            its own audit trail.
    """
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise ValueError(f"Tenant {tenant_id} not found")
    if not tenant.commission_wallet_enabled:
        raise ValueError(
            f"Tenant {tenant_id} has commission_wallet_enabled = false. "
            "Set it before running this backfill."
        )

    users = list(
        (await session.execute(select(User).where(User.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    if not apply:
        return await _count_missing(session, tenant_id, users)

    total = 0
    for user in users:
        total += await provision_user_accounts(
            session, tenant_id=tenant_id, user_id=user.id
        )
    return total


async def _count_missing(
    session: AsyncSession, tenant_id: UUID, users: list[User]
) -> int:
    """Count the commission wallets a real run would create. No writes."""
    from app.shared.models import Account

    currencies = await active_financial_currencies(session, tenant_id)
    held = {
        (row.user_id, row.currency)
        for row in (
            await session.execute(
                select(Account).where(
                    Account.tenant_id == tenant_id,
                    Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
                )
            )
        )
        .scalars()
        .all()
    }

    missing = 0
    for user in users:
        wanted = await wanted_account_types(session, tenant_id=tenant_id, user=user)
        if ACCOUNT_TYPE_COMMISSION_WALLET not in wanted:
            continue
        missing += sum(1 for c in currencies if (user.id, c) not in held)
    return missing


async def main(tenant_id: UUID, *, apply: bool) -> None:
    """Run the backfill and print what happened."""
    async with SessionLocal() as session:
        count = await backfill_tenant(session, tenant_id, apply=apply)
        if apply:
            await session.commit()
            print(f"Created {count} commission wallet account(s) for tenant {tenant_id}.")
        else:
            print(f"Dry run: {count} commission wallet(s) would be created.")
            print("Re-run with --apply to write.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print("Usage: python scripts/backfill_commission_wallets.py <tenant_id> [--apply]")
        raise SystemExit(2)
    asyncio.run(main(UUID(args[0]), apply="--apply" in sys.argv))
