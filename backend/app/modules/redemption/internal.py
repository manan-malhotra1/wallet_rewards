"""Internal redemption — points → fiat into the user's own wallet.

Module 11b (Pay-PRD-1200-1290, design doc 07 §6). The user burns points and
their financial wallet is credited at the tenant's configured conversion rate:

    points leg : DEBIT user points_account   → CREDIT points_redemption_wallet
    fiat leg   : DEBIT cashback_provider_wallet(currency) → CREDIT user wallet

`post_transaction` commits internally, so the pair is a two-step saga rather
than one DB transaction: the points BURN posts first (check + debit atomic
under the points FOR UPDATE lock, exactly like the external flow), then the
fiat PAYOUT (floored at the ledger choke point). A payout failure posts an
append-only compensating reversal of the burn — the user's points come back,
nothing is ever updated in place. Replays under the same Idempotency-Key are
self-healing: each leg dedupes on its derived key, so a crash between legs
resumes where it stopped. The `internal_redemptions` row binds the pair,
snapshots the rate, and both transactions carry `internal_redemption:<id>` in
`external_reference` (Pay-PRD-1260).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import UserPrincipal
from app.modules.accounts.service import derive_balance, lock_account_for_update
from app.modules.audit.service import record_audit_for_user
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.redemption.rates import resolve_active_rate
from app.modules.redemption.schemas import InternalRedemptionRequest
from app.modules.redemption.service import _assert_tenant_exists, _find_user_points_account
from app.modules.roles.service import require_permission
from app.shared.exceptions import AccountNotFound, InsufficientFunds
from app.shared.models import (
    ACCOUNT_TYPE_CASHBACK_PROVIDER,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_POINTS_REDEMPTION,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    InternalRedemption,
    Transaction,
)

# Base flow code for both legs — pricing/limits and step-up are scoped to the
# points side ("redemption", PTS), matching the external flow.
_BASE_SERVICE = "redemption"


async def get_or_create_system_account(
    session: AsyncSession, *, tenant_id: UUID, account_type: str, currency: str
) -> Account:
    """Fetch-or-create a system-owned account for a (tenant, type, currency).

    Lazy like the airtime holding / operator adjustment helpers, so a new
    tenant needs no pre-seeding. Called BEFORE any FOR UPDATE lock (it commits
    on create); on an INSERT race the loser re-reads the winner's row.
    """
    currency = currency.upper()
    stmt = select(Account).where(
        Account.tenant_id == tenant_id,
        Account.account_type == account_type,
        Account.currency == currency,
        Account.user_id.is_(None),
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    account = Account(tenant_id=tenant_id, account_type=account_type, currency=currency)
    session.add(account)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return (await session.execute(stmt)).scalar_one()
    await session.refresh(account)
    return account


async def _find_user_wallet(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, currency: str
) -> Account:
    """Return the user's financial wallet in `currency`, or 404 AccountNotFound."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.currency == currency.upper(),
        )
    )
    wallet = result.scalar_one_or_none()
    if wallet is None:
        raise AccountNotFound()
    return wallet


def quote_fiat_amount(
    points_amount: Decimal, *, points_per_unit: Decimal, value_per_unit: Decimal
) -> Decimal:
    """Convert points to fiat at the configured rate, rounded to 2 minor units.

    ROUND_HALF_UP on the user-facing amount; the rate snapshot on the pair row
    keeps the conversion reconstructible after later rate changes.
    """
    raw = points_amount * value_per_unit / points_per_unit
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _burn_points(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    user_points: Account,
    points_sink: Account,
    points_amount: Decimal,
    idempotency_key: str,
) -> Transaction:
    """Post the points burn — balance check + debit atomic under the points lock.

    Redemption owns the points FOR UPDATE lock (design 07 §2.2): the ledger
    balance guard skips points accounts, so the derived-balance check here and
    the debit inside `post_transaction` (which commits, releasing the lock)
    are what serialise concurrent burns.

    Raises:
        InsufficientFunds (409): available points below `points_amount`.
    """
    await lock_account_for_update(session, user_points.id)
    balance, reserved = await derive_balance(session, user_points.id)
    if balance - reserved < points_amount:
        raise InsufficientFunds()

    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="redemption_internal",
            base_transaction_type=_BASE_SERVICE,
            currency=user_points.currency,
            entries=[
                LedgerEntryRequest(
                    account_id=user_points.id, entry_type=ENTRY_DEBIT, amount=points_amount
                ),
                LedgerEntryRequest(
                    account_id=points_sink.id, entry_type=ENTRY_CREDIT, amount=points_amount
                ),
            ],
            initiated_by=user_id,
            amount=points_amount,
        ),
    )


async def _unwind_burn(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    user_points: Account,
    points_sink: Account,
    points_amount: Decimal,
    idempotency_key: str,
) -> None:
    """Compensate a burn whose payout failed — append-only reversal legs.

    Opposite-direction entries in a NEW transaction (`{key}:unwind`), restoring
    the user's points (invariant #1 — never an UPDATE). `is_reversal=True`
    exempts the restore from any cap.
    """
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=f"{idempotency_key}:unwind",
            transaction_type="redemption_internal",
            base_transaction_type=_BASE_SERVICE,
            currency=user_points.currency,
            entries=[
                LedgerEntryRequest(
                    account_id=points_sink.id, entry_type=ENTRY_DEBIT, amount=points_amount
                ),
                LedgerEntryRequest(
                    account_id=user_points.id, entry_type=ENTRY_CREDIT, amount=points_amount
                ),
            ],
            initiated_by=user_id,
            amount=points_amount,
            is_reversal=True,
        ),
    )


async def initiate_internal_redemption(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    user: UserPrincipal | None = None,
    ip_address: str | None = None,
    request: InternalRedemptionRequest,
    idempotency_key: str,
) -> InternalRedemption:
    """Burn points and credit the user's wallet at the configured rate.

    Gate order mirrors the external `initiate_redemption` (design 07 §6.3):
    RBAC → step-up → conversion rate (FAIL-CLOSED) → idempotency fast-path →
    access lock → pricing/limits fail-closed → burn → payout (compensated on
    failure) → pair row + cross-references.

    Returns:
        The persisted InternalRedemption pair row (existing one on replay).

    Raises:
        ConversionRateMissing (422): no ACTIVE rate for the currency.
        AccountNotFound (404): user has no wallet in the currency.
        InsufficientFunds (409): points balance below `points_amount`.
        InsufficientCashbackFunds (409): cashback wallet can't cover the payout
            (the burn is compensated before this propagates).
        AppHTTPException: pricing/limits fail-closed 422s, RBAC 403, step-up 401.

    Side effects:
        Two COMPLETED ledger transactions (+ a compensating reversal on payout
        failure), one internal_redemptions row, one audit row.
    """
    await _assert_tenant_exists(session, tenant_id)
    await require_permission(session, user_id, _BASE_SERVICE)

    if user is not None:
        from app.modules.step_up.service import enforce_step_up

        await enforce_step_up(
            session,
            principal=user,
            transaction_type=_BASE_SERVICE,
            currency="PTS",
            amount=request.points_amount,
            pin=request.pin,
            ip_address=ip_address,
        )

    # FAIL-CLOSED rate gate (Pay-PRD-1220) — before any account work.
    rate = await resolve_active_rate(session, tenant_id, request.currency)
    fiat_amount = quote_fiat_amount(
        request.points_amount,
        points_per_unit=Decimal(rate.points_per_unit),
        value_per_unit=Decimal(rate.value_per_unit),
    )

    # Idempotency fast-path — a replay returns the original pair, no rework.
    existing = (
        await session.execute(
            select(InternalRedemption).where(
                InternalRedemption.tenant_id == tenant_id,
                InternalRedemption.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    from app.modules.identity.service import assert_user_can_transact

    await assert_user_can_transact(session, tenant_id=tenant_id, user_id=user_id)

    user_points = await _find_user_points_account(session, tenant_id, user_id)
    user_wallet = await _find_user_wallet(session, tenant_id, user_id, request.currency)

    # Fail-closed service gate (invariant #12) — points-scoped like the
    # external flow: BOTH a pricing and a limit config must resolve or 422.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=_BASE_SERVICE,
        account_type=ACCOUNT_TYPE_POINTS,
        currency=user_points.currency,
        user_id=user_id,
    )

    # System accounts BEFORE the points lock (their get_or_create commits).
    points_sink = await get_or_create_system_account(
        session,
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_POINTS_REDEMPTION,
        currency=user_points.currency,
    )
    cashback_wallet = await get_or_create_system_account(
        session,
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_CASHBACK_PROVIDER,
        currency=request.currency,
    )

    points_txn = await _burn_points(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        user_points=user_points,
        points_sink=points_sink,
        points_amount=request.points_amount,
        idempotency_key=idempotency_key,
    )

    # Fiat payout — the cashback wallet's choke-point floor rejects an
    # underfunded payout (409). The burn above is already durable, so a payout
    # failure MUST compensate it before propagating: the user's points come
    # back via append-only reversal legs, and the whole attempt nets to zero.
    try:
        payout_txn = await post_transaction(
            session,
            PostTransactionRequest(
                tenant_id=tenant_id,
                # Derived key: ONE client key covers the pair, so a replay after
                # a crash between the legs resumes idempotently.
                idempotency_key=f"{idempotency_key}:payout",
                transaction_type="redemption_internal_payout",
                base_transaction_type=_BASE_SERVICE,
                currency=cashback_wallet.currency,
                entries=[
                    LedgerEntryRequest(
                        account_id=cashback_wallet.id, entry_type=ENTRY_DEBIT, amount=fiat_amount
                    ),
                    LedgerEntryRequest(
                        account_id=user_wallet.id, entry_type=ENTRY_CREDIT, amount=fiat_amount
                    ),
                ],
                initiated_by=user_id,
                amount=fiat_amount,
            ),
        )
    except Exception:
        await _unwind_burn(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            user_points=user_points,
            points_sink=points_sink,
            points_amount=request.points_amount,
            idempotency_key=idempotency_key,
        )
        raise

    pair = InternalRedemption(
        tenant_id=tenant_id,
        user_id=user_id,
        points_transaction_id=points_txn.id,
        payout_transaction_id=payout_txn.id,
        currency=cashback_wallet.currency,
        points_amount=request.points_amount,
        fiat_amount=fiat_amount,
        points_per_unit=rate.points_per_unit,
        value_per_unit=rate.value_per_unit,
        idempotency_key=idempotency_key,
    )
    session.add(pair)
    await session.flush()

    # Cross-reference (Pay-PRD-1260): both transactions name the pair row, so
    # either leg resolves to the other via internal_redemptions.
    points_txn.external_reference = f"internal_redemption:{pair.id}"
    payout_txn.external_reference = f"internal_redemption:{pair.id}"

    if user is not None:
        record_audit_for_user(
            session,
            user,
            action="redemption.internal",
            entity_type="internal_redemption",
            entity_id=str(pair.id),
            after_state={
                "points_amount": str(request.points_amount),
                "fiat_amount": str(fiat_amount),
                "currency": cashback_wallet.currency,
            },
            ip_address=ip_address,
        )

    await session.commit()
    await session.refresh(pair)
    return pair
