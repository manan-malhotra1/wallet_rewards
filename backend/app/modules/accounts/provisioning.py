"""Per-user account provisioning — the single "which wallets should this user hold" rule.

Called from three places (spec 2026-08-26 §6): `identity.create_user`, the
instrument-create backfill, and `identity.change_user_type`. Keeping the rule in
one function is what stops those three drifting apart.

Lives in its own module rather than in `accounts/service.py` because it
orchestrates across instruments and user types; importing those from
`service.py` would create an import cycle.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    INSTRUMENT_STATUS_ACTIVE,
    Account,
    Instrument,
    Tenant,
    User,
)


async def wanted_account_types(
    session: AsyncSession, *, tenant_id: UUID, user: User
) -> list[str]:
    """The account types this user should hold per financial currency.

    Every user gets a `financial_wallet` — the MAIN wallet — regardless of
    category (spec D12). Eligible users on a flag-on tenant additionally get a
    `commission_wallet` (D4).

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope.
        user: The user being provisioned for.

    Returns:
        One or two account-type strings, main wallet first.
    """
    types = [ACCOUNT_TYPE_FINANCIAL_WALLET]

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None or not tenant.commission_wallet_enabled:
        return types

    if await is_commission_wallet_eligible(session, tenant_id, user.user_type):
        types.append(ACCOUNT_TYPE_COMMISSION_WALLET)
    return types


async def active_financial_currencies(
    session: AsyncSession, tenant_id: UUID
) -> list[str]:
    """Codes of the tenant's live financial instruments.

    Points instruments are excluded: `rewards` auto-provisions points accounts
    on its own, and there is no commission wallet for a points unit.
    """
    return list(
        (
            await session.execute(
                select(Instrument.code).where(
                    Instrument.tenant_id == tenant_id,
                    Instrument.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                    Instrument.status == INSTRUMENT_STATUS_ACTIVE,
                    Instrument.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )


async def provision_user_accounts(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> int:
    """Create every account this user should hold but does not yet.

    One `financial_wallet` per active financial instrument for EVERY user —
    this closes the pre-existing gap where a user created after the last
    instrument held no wallet at all and 404'd with AccountNotFound on their
    first cash-in (spec §2, D12). Plus one `commission_wallet` per active
    financial instrument when the tenant flag is on and the user's type is in
    the Retail or Business category (D4).

    Idempotent by construction — existing (user, type, currency) tuples are
    skipped — so every caller may invoke it unconditionally.

    Args:
        session: Async DB session. Rows are ADDED and flushed but NOT
            committed; the caller commits, so provisioning joins the caller's
            transaction and a failed user create leaves no orphaned accounts.
        tenant_id: Tenant scope.
        user_id: The user to provision for.

    Returns:
        Number of new Account rows added.

    Side effects:
        Adds 0..N Account rows in the caller's transaction.
    """
    user = (
        await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        return 0

    currencies = await active_financial_currencies(session, tenant_id)
    if not currencies:
        return 0

    wanted = await wanted_account_types(session, tenant_id=tenant_id, user=user)

    held = {
        (row.account_type, row.currency)
        for row in (
            await session.execute(
                select(Account).where(
                    Account.tenant_id == tenant_id, Account.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    }

    added = 0
    for currency in currencies:
        for account_type in wanted:
            if (account_type, currency) in held:
                continue
            session.add(
                Account(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_type=account_type,
                    currency=currency,
                )
            )
            added += 1
    if added:
        await session.flush()
    return added
