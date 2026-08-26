"""Commission payout targets — which account each leg credits.

Split out of `service.py` so the CRUD half stays readable: this module owns
parent walking, category eligibility and wallet lookup, and `service.py` owns
config maths and admin CRUD.

Every unpayable-PARENT path returns a REASON rather than raising (spec
2026-08-26, D10). A standalone agent with no super-agent is the normal case and
must never block their cash-in. The EARNER's own leg is different: a missing
account there means a rule was configured for a user who cannot receive it, and
the caller fails closed (spec §7.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    User,
)

DESTINATION_MAIN = "main_wallet"
DESTINATION_COMMISSION = "commission_wallet"

# Recorded on the transaction when the parent leg does not pay.
SKIP_NO_PARENT = "no_parent"
SKIP_PARENT_INELIGIBLE = "parent_ineligible_category"
SKIP_PARENT_WALLET_MISSING = "parent_wallet_missing"
SKIP_PARENT_ZERO_RATE = "parent_zero_rate"


@dataclass(frozen=True)
class PayoutTarget:
    """One commission leg's destination.

    Attributes:
        account_id: The account to CREDIT, or None when the leg does not pay.
        skip_reason: Why it does not pay. None when `account_id` is set.
    """

    account_id: UUID | None
    skip_reason: str | None


def account_type_for(destination: str) -> str:
    """Map a config destination to the account type that receives the credit."""
    return (
        ACCOUNT_TYPE_COMMISSION_WALLET
        if destination == DESTINATION_COMMISSION
        else ACCOUNT_TYPE_FINANCIAL_WALLET
    )


async def _find_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    account_type: str,
    currency: str,
) -> Account | None:
    """Return one user's account of a type/currency, or None."""
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == account_type,
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one_or_none()


async def resolve_earner_target(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    earner_user_id: UUID,
    destination: str,
    currency: str,
) -> PayoutTarget:
    """Resolve where the EARNER's own commission is credited.

    Unlike the parent leg this does NOT fail open: a missing account here means
    a rule was configured for a user who cannot receive it, and the caller must
    422 before any ledger write (spec §7.2, invariant #12 discipline). Silently
    paying spendable commission where a review hold was configured is the exact
    failure mode this feature exists to prevent.

    Returns:
        A PayoutTarget. `skip_reason` is set only when no account resolved.
    """
    account = await _find_wallet(
        session,
        tenant_id=tenant_id,
        user_id=earner_user_id,
        account_type=account_type_for(destination),
        currency=currency,
    )
    if account is None:
        return PayoutTarget(None, SKIP_PARENT_WALLET_MISSING)
    return PayoutTarget(account.id, None)


async def resolve_parent_target(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    earner_user_id: UUID,
    destination: str,
    currency: str,
) -> PayoutTarget:
    """Resolve where the earner's PARENT commission is credited.

    Walks EXACTLY ONE level via `users.parent_user_id` — never a chain (D9),
    consistent with the two-level type-hierarchy cap (user-types D7).

    The parent leg lands in the same KIND of wallet the child's rule names
    (D6): a commission-wallet rule holds the parent's share for review too.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — a cross-tenant parent never resolves.
        earner_user_id: The acting earner whose parent is being paid.
        destination: The rule's `payout_destination`.
        currency: ISO 4217 of the commission.

    Returns:
        A PayoutTarget whose `skip_reason` is set for every unpayable case.
        Never raises — that is what fail-open means here.
    """
    earner = (
        await session.execute(
            select(User).where(User.id == earner_user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if earner is None or earner.parent_user_id is None:
        return PayoutTarget(None, SKIP_NO_PARENT)

    parent = (
        await session.execute(
            select(User).where(
                User.id == earner.parent_user_id, User.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        return PayoutTarget(None, SKIP_NO_PARENT)

    # Impossible by construction (the hierarchy validation at user create plus
    # ck_user_types_no_self_parent), asserted anyway per spec §7.1: a self-loop
    # here would double-credit one account in a single balanced transaction.
    assert parent.id != earner_user_id, "parent_user_id must never be self"

    if not await is_commission_wallet_eligible(session, tenant_id, parent.user_type):
        return PayoutTarget(None, SKIP_PARENT_INELIGIBLE)

    account = await _find_wallet(
        session,
        tenant_id=tenant_id,
        user_id=parent.id,
        account_type=account_type_for(destination),
        currency=currency,
    )
    if account is None:
        return PayoutTarget(None, SKIP_PARENT_WALLET_MISSING)
    return PayoutTarget(account.id, None)
