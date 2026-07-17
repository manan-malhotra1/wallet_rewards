"""Change-PIN service — user self-service PIN change (charged, Pay-PRD-0420).

A user changes their own PIN. This is a CHARGED service and so runs the same
fail-closed gate every money path does (invariant #12): it may proceed only when
BOTH a pricing config AND a limit config resolve for the acting user's type. It
differs from every other charged service in having NO principal — when the
configured fee is zero there are no ledger legs at all (`post_transaction`
requires >= 2 balanced entries), yet the operation must still be idempotent and
audited. The `pin_changes` domain row carries idempotency independent of any
ledger transaction (mirroring `AirtimeRecharge`).

Order of operations mirrors the canonical charged-service shape (cash-out):
idempotency fast-path -> load user + verify CURRENT pin (login-grade lockout)
-> validate NEW pin -> invariant #12 gate -> pricing/tax -> limits -> assemble
fee-only legs -> advisory overdraft -> post_transaction (authoritative balance
guard + atomic commit). The current-PIN check is the only gate on the operation
(changing one's own PIN is universal self-service), so there is no role check.

NFR-0170: no PIN, PIN hash, or anything derived from it is EVER logged, stored,
audited, or returned. The audit before/after carries only the charge breakdown.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_pin, verify_pin
from app.auth.lockout import (
    is_locked,
    lockout_seconds_remaining,
    register_failure,
    reset_failures,
)
from app.auth.principals import UserPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_user
from app.modules.identity.service import _validate_pin_format
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.pin_change.schemas import ChangePinRequest
from app.modules.pricing.assembler import (
    ChargeAccounts,
    ChargeAmounts,
    ChargeFlags,
    assemble_charges,
)
from app.shared.exceptions import (
    AccountLocked,
    AccountNotFound,
    InsufficientFunds,
    InvalidCredentials,
    NewPinSameAsCurrent,
    PinNotSet,
    UserNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_DEBIT,
    PIN_CHANGE_STATUS_COMPLETED,
    Account,
    AuthAttempt,
    PinChange,
    User,
)

# Service code == transaction_type == the key pricing / limits / gate all use.
CHANGE_PIN_SERVICE_CODE = "change_pin"


async def _find_user_wallet(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, currency: str
) -> Account:
    """Return the user's `financial_wallet` for the currency, or 404."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.currency == currency.upper(),
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFound()
    return account


def _net_debit(entries: list[LedgerEntryRequest], account_id: UUID) -> Decimal:
    """Net DEBIT (debits - credits) an account bears across the legs."""
    total = Decimal("0")
    for entry in entries:
        if entry.account_id != account_id:
            continue
        total += entry.amount if entry.entry_type == ENTRY_DEBIT else -entry.amount
    return total


async def _verify_current_pin(
    session: AsyncSession,
    user: User,
    current_pin: str,
    *,
    ip_address: str | None,
) -> None:
    """Verify the CURRENT pin with login-grade lockout, or raise.

    Reuses the exact lockout semantics of `identity.authenticate_pin` so that
    brute-forcing the current PIN through the change-PIN endpoint is throttled
    identically to login: a miss writes a failed `AuthAttempt`, bumps the Redis
    failure counter, and locks the account when the threshold trips. A success
    resets the counter.

    Raises:
        AccountLocked (423): already locked, or the failure just tripped it.
        PinNotSet (401): the user never completed PIN setup.
        InvalidCredentials (401): the current PIN is wrong.
    """
    # Check lockout BEFORE comparing the PIN — a locked-out attacker who happens
    # to guess right must still be refused (mirrors authenticate_pin).
    if await is_locked(user.id):
        raise AccountLocked(await lockout_seconds_remaining(user.id))

    if user.pin_hash is None:
        raise PinNotSet()

    if not verify_pin(current_pin, user.pin_hash):
        session.add(
            AuthAttempt(
                user_id=user.id,
                attempt_type="pin",
                success=False,
                ip_address=ip_address,
            )
        )
        await session.commit()
        await register_failure(user.id)
        if await is_locked(user.id):
            raise AccountLocked(await lockout_seconds_remaining(user.id))
        raise InvalidCredentials()

    # Success — clear the failure counter so prior misses don't haunt the user.
    await reset_failures(user.id)


def _record_pin_change_audit(
    session: AsyncSession,
    principal: UserPrincipal,
    pin_change: PinChange,
    *,
    ip_address: str | None,
) -> None:
    """Audit `pin.changed` with the charge breakdown ONLY (NFR-0170).

    The before/after state deliberately carries no PIN, no hash, and nothing
    derived from either — only currency / fee / tax / status / transaction_id.
    """
    record_audit_for_user(
        session,
        principal,
        action="pin.changed",
        entity_type="pin_change",
        entity_id=str(pin_change.id),
        after_state={
            "currency": pin_change.currency,
            "fee": str(pin_change.fee_amount),
            "tax": str(pin_change.tax_amount),
            "status": pin_change.status,
            "transaction_id": (
                str(pin_change.transaction_id) if pin_change.transaction_id else None
            ),
        },
        ip_address=ip_address,
    )


async def change_pin(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    request: ChangePinRequest,
    idempotency_key: str,
    principal: UserPrincipal,
    ip_address: str | None = None,
) -> PinChange:
    """Change the acting user's PIN, charging the configured fee (invariant #12).

    Args:
        session: Async DB session (committed inside — via `post_transaction`
            when a fee is charged, or directly for a zero-fee change).
        tenant_id: Tenant scope (from the session token, never the body).
        user_id: The acting user — always resolved from auth, never trusted
            from the request.
        request: Validated {current_pin, new_pin, currency}.
        idempotency_key: Unique per tenant; a replay returns the original
            `PinChange` without re-verifying or re-charging.
        principal: The authenticated user principal (audit actor).
        ip_address: Caller IP for the audit trail + failed-attempt row.

    Returns:
        The persisted (or already-existing) `PinChange`.

    Raises:
        UserNotFound (404): unknown user, or one in another tenant.
        AccountLocked (423) / PinNotSet (401) / InvalidCredentials (401):
            current-PIN verification (login-grade lockout).
        InvalidPinFormat (422): the new PIN isn't 4-6 numeric digits.
        NewPinSameAsCurrent (422): the new PIN equals the current one.
        ServiceNotConfigured (422): pricing OR limit config for `change_pin`
            is missing for the user's type (invariant #12).
        AccountNotFound (404): a fee is charged but the user has no wallet.
        InsufficientFunds (409): the wallet can't cover the fee + tax.

    Side effects:
        Sets `users.pin_hash`, inserts a `pin_changes` row, and (when the fee is
        non-zero) posts a fee-only double-entry transaction — all in one atomic
        commit. Appends one `pin.changed` audit row.
    """
    # 1. Idempotency fast-path — a replay returns the original row before any
    # PIN verification or charge (Pay-PRD-0200).
    existing = (
        await session.execute(
            select(PinChange).where(
                PinChange.tenant_id == tenant_id,
                PinChange.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # 2. Load the user (tenant-scoped) and verify the CURRENT pin with lockout.
    user = (
        await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise UserNotFound()
    await _verify_current_pin(session, user, request.current_pin, ip_address=ip_address)

    # 3. Validate the new PIN and reject a no-op change (which would still charge).
    _validate_pin_format(request.new_pin)
    if request.new_pin == request.current_pin:
        raise NewPinSameAsCurrent()

    currency = request.currency.upper()

    # 4. Invariant #12 gate (UNCONDITIONAL): BOTH a pricing AND a limit config
    # must resolve for the acting user's type, or reject BEFORE any charge work.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=CHANGE_PIN_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        user_id=user_id,
    )

    # 5. Pricing (fixed fee — no principal, so amount=0 zeroes any variable part)
    # + tax on that fee. The gate above proved a config exists, so a missing
    # band here is a real gap and `resolve_fee` raises 422 (no silent zero-fee).
    from app.modules.pricing.service import resolve_fee
    from app.modules.taxes.service import calculate_tax

    fee_quote = await resolve_fee(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type=CHANGE_PIN_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=Decimal("0"),
    )
    fee = fee_quote.fee
    tax = await calculate_tax(
        session, tenant_id=tenant_id, currency=currency, fee=fee, commission=Decimal("0")
    )

    # 6. Limits. Change-PIN has no principal, so the resolved FEE is the amount
    # the limit config bounds (the fee charged, not a money movement).
    from app.modules.limits.service import check_limits

    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type=CHANGE_PIN_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=fee,
    )

    # 7. Stage the PIN mutation + the domain row so they commit ATOMICALLY with
    # the charge (post_transaction's single commit). fee/tax on the row are the
    # source-of-truth breakdown whether or not any ledger leg is emitted.
    user.pin_hash = hash_pin(request.new_pin)
    pin_change = PinChange(
        tenant_id=tenant_id,
        user_id=user_id,
        currency=currency,
        fee_amount=fee,
        tax_amount=tax.fee_tax,
        transaction_id=None,
        status=PIN_CHANGE_STATUS_COMPLETED,
        idempotency_key=idempotency_key,
    )
    session.add(pin_change)
    await session.flush()

    # 8. Charge only when there is money to move. A zero fee (and zero tax) emits
    # NO legs — post_transaction needs >= 2 balanced entries — so the change
    # commits on its own below. Assemble via the shared matrix so the
    # inclusive/exclusive tax handling stays single-sourced; the fee is always
    # EXCLUSIVE here (no principal to carve it from) and commission is always 0.
    if fee > 0 or tax.fee_tax > 0:
        from app.modules.pricing.service import (
            get_or_create_system_fee_account,
            get_or_create_system_tax_service,
        )

        wallet = await _find_user_wallet(
            session, tenant_id=tenant_id, user_id=user_id, currency=currency
        )
        fee_account = await get_or_create_system_fee_account(
            session, tenant_id=tenant_id, currency=currency
        )
        service_tax_account = await get_or_create_system_tax_service(
            session, tenant_id=tenant_id, currency=currency
        )
        assembled = assemble_charges(
            ChargeAccounts(
                payer_account_id=wallet.id,
                beneficiary_account_id=wallet.id,  # principal 0 -> no credit leg
                fee_account_id=fee_account.id,
                service_tax_account_id=service_tax_account.id,
                # Commission is structurally 0 for change-PIN, so these three
                # slots emit no legs; the wallet id is a harmless placeholder.
                commission_tax_account_id=wallet.id,
                commission_pool_account_id=wallet.id,
                agent_account_id=wallet.id,
            ),
            ChargeAmounts(
                principal=Decimal("0"),
                fee=fee,
                commission=Decimal("0"),
                fee_tax=tax.fee_tax,
                commission_tax=Decimal("0"),
            ),
            ChargeFlags(
                fee_inclusive=False,
                fee_tax_inclusive=tax.fee_tax_inclusive,
                commission_tax_inclusive=tax.commission_tax_inclusive,
            ),
        )

        # Advisory overdraft early-error — the AUTHORITATIVE guard is the
        # row-locked check inside post_transaction (invariant #11).
        balance, reserved = await derive_balance(session, wallet.id)
        if balance - reserved < _net_debit(assembled.entries, wallet.id):
            raise InsufficientFunds()

        # Commits pin_hash + PinChange + the fee transaction together.
        txn = await post_transaction(
            session,
            PostTransactionRequest(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                transaction_type=CHANGE_PIN_SERVICE_CODE,
                currency=currency,
                entries=assembled.entries,
                initiated_by=user_id,
                amount=fee,
                fee_amount=assembled.fee_amount,
                tax_amount=assembled.tax_amount,
            ),
        )
        # Cosmetic backfill of the applied transaction id (a 2nd commit is fine,
        # mirroring the money-operations applied-id pattern).
        pin_change.transaction_id = txn.id

    # 9. Audit (NFR-0250) + final commit. For a zero-fee change this is the ONLY
    # commit (pin_hash + PinChange + audit); for a charged change it also lands
    # the transaction_id backfill.
    _record_pin_change_audit(session, principal, pin_change, ip_address=ip_address)
    await session.commit()
    await session.refresh(pin_change)
    return pin_change
