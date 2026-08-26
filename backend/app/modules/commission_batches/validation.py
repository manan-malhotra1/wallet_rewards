"""Pass-1 batch row validation — spec 2026-08-26 §8.2.

Runs at UPLOAD so the checker only ever sees rows that could post. Every
failure is per-row and recoverable: the maker downloads the rejects, fixes them
and submits a new batch (D15). Nothing here raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.provisioning import active_financial_currencies
from app.modules.accounts.service import derive_balance
from app.modules.commission_batches.csv_io import ParsedRow
from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    Account,
    User,
    UserIdentifier,
)
from app.shared.utils.normalize import normalize_identifier

REASON_MSISDN_NOT_FOUND = "msisdn_not_found"
REASON_USER_NOT_ELIGIBLE = "user_not_eligible"
REASON_UNKNOWN_CURRENCY = "unknown_currency"
REASON_WALLET_MISSING = "commission_wallet_missing"
REASON_INVALID_AMOUNT = "invalid_amount"
REASON_INSUFFICIENT = "insufficient_commission_balance"
REASON_DUPLICATE = "duplicate_row"


@dataclass(frozen=True)
class ValidatedRow:
    """A parsed row plus what validation resolved, or why it could not.

    Attributes:
        parsed: The original row, preserved so a rejects file can echo it back.
        resolved_user_id: The tenant user the MSISDN mapped to, or None.
        resolved_account_id: Their commission wallet in this currency, or None.
        balance_snapshot: AVAILABLE balance (balance - reserved) at validation.
        snapshot_at: When that balance was read, so the checker can judge its age.
        failure_reason: Machine code, or None when the row is valid.
    """

    parsed: ParsedRow
    resolved_user_id: UUID | None
    resolved_account_id: UUID | None
    balance_snapshot: Decimal | None
    snapshot_at: datetime | None
    failure_reason: str | None


async def validate_rows(
    session: AsyncSession, *, tenant_id: UUID, rows: list[ParsedRow]
) -> list[ValidatedRow]:
    """Validate every row, resolving users, wallets and balances.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — a user in another tenant never resolves.
        rows: Parsed rows, in file order.

    Returns:
        One ValidatedRow per input row, IN ORDER — callers rely on the
        positional correspondence to build the rejects file.

    Notes:
        Duplicate (msisdn, currency) pairs keep the FIRST occurrence and reject
        the rest, so re-running the same file produces the same outcome. The
        same MSISDN with a DIFFERENT currency is not a duplicate — a user may
        legitimately be paid out of two commission wallets in one run.
    """
    currencies = set(await active_financial_currencies(session, tenant_id))

    seen: set[tuple[str, str]] = set()
    results: list[ValidatedRow] = []

    for row in rows:
        reason: str | None = None
        user: User | None = None
        account: Account | None = None
        available: Decimal | None = None
        snapshot_at: datetime | None = None

        key = (row.msisdn, row.currency)
        if key in seen:
            reason = REASON_DUPLICATE
        elif row.amount is None or row.amount <= Decimal("0"):
            reason = REASON_INVALID_AMOUNT
        elif row.currency not in currencies:
            reason = REASON_UNKNOWN_CURRENCY
        else:
            user = await _resolve_user(session, tenant_id, row.msisdn)
            if user is None:
                reason = REASON_MSISDN_NOT_FOUND
            elif not await is_commission_wallet_eligible(
                session, tenant_id, user.user_type
            ):
                reason = REASON_USER_NOT_ELIGIBLE
            else:
                account = await _commission_wallet(
                    session, tenant_id, user.id, row.currency
                )
                if account is None:
                    reason = REASON_WALLET_MISSING
                else:
                    balance, reserved = await derive_balance(session, account.id)
                    available = balance - reserved
                    snapshot_at = datetime.now(UTC)
                    if row.amount > available:
                        reason = REASON_INSUFFICIENT

        if reason is None:
            seen.add(key)

        results.append(
            ValidatedRow(
                parsed=row,
                resolved_user_id=user.id if user is not None else None,
                resolved_account_id=account.id if account is not None else None,
                balance_snapshot=available,
                snapshot_at=snapshot_at,
                failure_reason=reason,
            )
        )

    return results


async def _resolve_user(
    session: AsyncSession, tenant_id: UUID, msisdn: str
) -> User | None:
    """Resolve an MSISDN to a user in THIS tenant, via the canonical form.

    Normalising first is essential: identifiers are stored canonically, so a raw
    "27831234567" pasted from a spreadsheet would otherwise miss a stored
    "+27 83 123 4567" and every row would reject as msisdn_not_found.
    """
    try:
        canonical = normalize_identifier("phone", msisdn)
    except Exception:
        # A malformed phone is a row-level reject, never a batch-level crash.
        return None

    identifier = (
        await session.execute(
            select(UserIdentifier).where(
                UserIdentifier.tenant_id == tenant_id,
                UserIdentifier.identifier_type == "phone",
                UserIdentifier.identifier_value == canonical,
            )
        )
    ).scalar_one_or_none()
    if identifier is None:
        return None
    return (
        await session.execute(
            select(User).where(
                User.id == identifier.user_id, User.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def _commission_wallet(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, currency: str
) -> Account | None:
    """One user's commission wallet in a currency, or None."""
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
                Account.currency == currency,
            )
        )
    ).scalar_one_or_none()
