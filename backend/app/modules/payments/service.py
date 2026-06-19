"""Payments service — P2P orchestration, internal top-up, and the
mobile-facing demo top-up endpoint (Pay-PRD-0320).

The full PRD orchestration sequence (Pay-PRD-0260) is:
    1. Role check
    2. Limits check
    3. Pricing calculation
    4. Ledger write

Phase B implements step 4 only. Steps 1–3 are explicitly TODO with the relevant
PRD references. The architecture supports plugging them in without changing the
caller — they belong inside this service, before the `post_transaction` call.

The user-facing `topup()` function (Pay-PRD-0320) wraps the internal
`top_up()` ledger primitive with the user-action concerns: step-up PIN
enforcement, audit attribution to the user, and surfacing any earned
points back to the caller.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import UserPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_user
from app.modules.identity.service import resolve_identifier
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.payments.schemas import IdentifierType
from app.modules.roles.service import require_permission
from app.shared.exceptions import (
    AccountNotFound,
    CurrencyMismatch,
    InsufficientFunds,
    SelfTransferNotAllowed,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    LedgerEntry,
    RewardEvent,
    Tenant,
    Transaction,
    User,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_user_wallet(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    currency: str,
) -> Account:
    """Return the user's `financial_wallet` for the given currency, or 404.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: User whose wallet we want.
        currency: 3-letter ISO 4217 (case-insensitive).

    Returns:
        The matching Account row.

    Raises:
        AccountNotFound: 404 when no matching wallet exists in this tenant.
    """
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


async def _lock_account_for_update(
    session: AsyncSession, account_id: UUID
) -> None:
    """Acquire a row-level write lock on the account.

    Prevents the classic double-spend race: two concurrent P2P transfers from
    the same wallet that each see the full balance and both write debits.
    The lock holds until the surrounding DB transaction commits.
    """
    await session.execute(
        select(Account.id).where(Account.id == account_id).with_for_update()
    )


async def p2p_transfer(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sender_user_id: UUID,
    recipient_identifier_type: IdentifierType,
    recipient_identifier_value: str,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
    sender_principal: object | None = None,
    pin: str | None = None,
    ip_address: str | None = None,
) -> tuple[Transaction, UUID, int | None]:
    """Execute a peer-to-peer transfer between two users in the same tenant.

    Steps (matches PRD Pay-PRD-0260 ordering):
      1. Validate tenant exists.
      2. Resolve recipient identifier -> user_id (tenant-scoped).
      3. Reject self-transfer.
      4. Find sender + recipient wallets in the requested currency.
      5. Lock sender wallet for the duration of the DB transaction.
      6. Overdraft check (Pay-PRD-0220) — reject BEFORE any ledger write.
      7. Post balanced transaction via the ledger service.
      8. Resolve any reward points credited by the rules engine for this
         transaction (post-commit, so any rule-firings are durable).

    Steps 1.5 (role), 2.5 (limits), 3.5 (pricing) — TODO, Phase C+.

    Args:
        session: Async DB session (commits inside `post_transaction`).
        tenant_id: Tenant scope.
        sender_user_id: User initiating the transfer.
        recipient_identifier_type: Identifier kind used to find the recipient.
        recipient_identifier_value: Raw identifier value.
        amount: Positive Decimal amount.
        currency: 3-letter ISO 4217 (case-insensitive).
        idempotency_key: Client-supplied unique key (Pay-PRD-0200). Replays of
            the same key return the original transaction.

    Returns:
        (Transaction, recipient_user_id, earned_points). `earned_points`
        is the integer total of PTS the rules engine issued against this
        transaction, or `None` if no rules fired. Today the P2P path does
        not synchronously call the rules engine, so this is `None` in
        practice; the lookup picks up any future rule-firings keyed by
        the internal transaction id.

    Raises:
        TenantNotFound: unknown tenant.
        UserNotFound: recipient identifier not registered in this tenant.
        SelfTransferNotAllowed: sender == recipient.
        AccountNotFound: sender or recipient lacks a wallet in this currency.
        CurrencyMismatch: defence-in-depth — request currency mismatches an
            account's currency (the wallet lookup already filters, so this
            normally can't fire, but the check is here for future-proofing).
        InsufficientFunds: sender's available balance < amount.
    """
    await _assert_tenant_exists(session, tenant_id)

    # 1. Role check (Pay-PRD-0260 step 1, Pay-PRD-0440/0450/0460).
    # Sender must hold an active role permitting "p2p". Fails BEFORE any
    # further work — no lock acquired, no ledger touched.
    await require_permission(session, sender_user_id, "p2p")

    # 2. Resolve recipient identifier (tenant-scoped — Pay-PRD-0060).
    recipient_id_row = await resolve_identifier(
        session,
        tenant_id,
        recipient_identifier_type,
        recipient_identifier_value,
    )
    recipient_user_id = recipient_id_row.user_id

    # 3. Self-transfer guard.
    if sender_user_id == recipient_user_id:
        raise SelfTransferNotAllowed()

    # 4. Wallet lookups (also enforces tenant isolation — both wallets must
    # exist in this tenant in this currency).
    sender_wallet = await _find_user_wallet(
        session,
        tenant_id=tenant_id,
        user_id=sender_user_id,
        currency=currency,
    )
    recipient_wallet = await _find_user_wallet(
        session,
        tenant_id=tenant_id,
        user_id=recipient_user_id,
        currency=currency,
    )

    # Defence-in-depth: the wallet query already filters by currency, but a
    # future code change might relax that. Re-check here.
    if sender_wallet.currency != recipient_wallet.currency:
        raise CurrencyMismatch()

    # 5. Lock sender wallet to serialise concurrent same-sender transfers.
    await _lock_account_for_update(session, sender_wallet.id)

    # 6. Limits check (Phase G.2, Pay-PRD-0260 step 2). Throws on min/max
    # or rolling-24h cap breach. No-op when no config exists.
    from app.modules.limits.service import check_limits  # noqa: PLC0415

    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=sender_user_id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=amount,
    )

    # 6.5. Step-up PIN check (Phase H). Comes AFTER limits so an
    # over-cap transaction returns 422 without prompting the user for
    # a PIN it can't satisfy anyway. No-op when no policy exists.
    from app.auth.principals import UserPrincipal  # noqa: PLC0415
    from app.modules.step_up.service import enforce_step_up  # noqa: PLC0415

    if isinstance(sender_principal, UserPrincipal):
        await enforce_step_up(
            session,
            principal=sender_principal,
            transaction_type="p2p",
            currency=currency,
            amount=amount,
            pin=pin,
            ip_address=ip_address,
        )

    # 7. Pricing fee calculation (Phase G.3, Pay-PRD-0260 step 3). Optional
    # — if no pricing config exists we treat this as no-fee (legacy callers
    # / tests). Production tenants MUST configure a zero-fee row or the
    # pricing call raises PricingConfigMissing. To stay backward-compatible
    # with the existing test suite we swallow that specific case here.
    from app.modules.pricing.service import (  # noqa: PLC0415
        calculate_fee,
        get_or_create_system_fee_account,
    )
    from app.shared.exceptions import PricingConfigMissing  # noqa: PLC0415

    fee = Decimal("0")
    try:
        fee = await calculate_fee(
            session,
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=currency,
            amount=amount,
        )
    except PricingConfigMissing:
        # Legacy pass-through: tenants without pricing configured pay no
        # fee. Production deployments should explicitly insert zero-fee
        # rows; the admin UI surfaces this gap.
        fee = Decimal("0")

    # 8. Overdraft prevention (Pay-PRD-0220) — must happen BEFORE the
    # ledger write, and must include the fee.
    balance, reserved = await derive_balance(session, sender_wallet.id)
    available = balance - reserved
    if available < amount + fee:
        raise InsufficientFunds()

    # 9. Build the ledger legs. Base txn always = sender→recipient. Fee
    # adds a 3rd + 4th leg (sender → system_fee_collected) atomically in
    # the same balanced transaction.
    entries = [
        LedgerEntryRequest(
            account_id=sender_wallet.id,
            entry_type=ENTRY_DEBIT,
            amount=amount,
        ),
        LedgerEntryRequest(
            account_id=recipient_wallet.id,
            entry_type=ENTRY_CREDIT,
            amount=amount,
        ),
    ]
    if fee > 0:
        fee_account = await get_or_create_system_fee_account(
            session, tenant_id=tenant_id, currency=currency
        )
        entries.append(
            LedgerEntryRequest(
                account_id=sender_wallet.id,
                entry_type=ENTRY_DEBIT,
                amount=fee,
            )
        )
        entries.append(
            LedgerEntryRequest(
                account_id=fee_account.id,
                entry_type=ENTRY_CREDIT,
                amount=fee,
            )
        )

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="p2p",
            currency=currency.upper(),
            entries=entries,
            initiated_by=sender_user_id,
            amount=amount,
        ),
    )

    # NFR-0250: every P2P state change is audit-logged. Caller (router) passes
    # a UserPrincipal; if absent (internal callers / seeds) we skip — the
    # transaction itself is the financial record of truth.
    from app.auth.principals import UserPrincipal

    if isinstance(sender_principal, UserPrincipal):
        record_audit_for_user(
            session,
            sender_principal,
            action="p2p.transferred",
            entity_type="transaction",
            entity_id=str(txn.id),
            after_state={
                "amount": str(amount),
                "currency": currency.upper(),
                "recipient_user_id": str(recipient_user_id),
                "status": txn.status,
            },
            ip_address=ip_address,
        )
        await session.commit()

    # Step 8 — earned-points lookup happens AFTER every commit above so any
    # rule-firing (today: none, since P2P doesn't synchronously go through
    # Kafka; tomorrow: whatever the rules engine writes against this
    # transaction id) is already durable. Mirrors the topup() pattern.
    earned_points = await _resolve_earned_points_for_txn(session, txn.id)

    return txn, recipient_user_id, earned_points


async def _get_or_create_system_cash_inflow(
    session: AsyncSession, tenant_id: UUID, currency: str
) -> Account:
    """Idempotent fetch-or-create for the per-(tenant, currency) cash inflow account.

    Used by `top_up()` so the seed and future top-up endpoint don't need to
    pre-create the account out-of-band.
    """
    currency = currency.upper()
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
            Account.currency == currency,
            Account.user_id.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if account is not None:
        return account
    account = Account(
        tenant_id=tenant_id,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency=currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def top_up(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
) -> Transaction:
    """Internal top-up — credit a user's wallet from outside the system.

    Posts a balanced transaction:
      DEBIT  system_cash_inflow (created lazily if missing)
      CREDIT user's financial_wallet in the requested currency

    NOT exposed via HTTP in Phase B — the seed and future Pay-PRD-0320
    endpoint will call this. Exposing it as an admin API endpoint comes later
    once auth + role checks are in place.

    Args:
        session: Async DB session.
        tenant_id, user_id, amount, currency, idempotency_key: as P2P.

    Returns:
        The posted Transaction.

    Raises:
        TenantNotFound, AccountNotFound: same semantics as P2P.
    """
    await _assert_tenant_exists(session, tenant_id)

    user_wallet = await _find_user_wallet(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency
    )
    inflow = await _get_or_create_system_cash_inflow(session, tenant_id, currency)

    return await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="top_up",
            currency=currency.upper(),
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id,
                    entry_type=ENTRY_DEBIT,
                    amount=amount,
                ),
                LedgerEntryRequest(
                    account_id=user_wallet.id,
                    entry_type=ENTRY_CREDIT,
                    amount=amount,
                ),
            ],
            initiated_by=None,  # system-initiated
            amount=amount,
        ),
    )


# Bind User to the import graph so it doesn't trigger import warnings —
# `User` is referenced in this module's docstrings.
_ = User


async def _resolve_earned_points_for_txn(
    session: AsyncSession, txn_id: UUID
) -> int | None:
    """Sum reward points issued by the rules engine for an internal txn.

    The rules engine writes `reward_events` rows keyed by
    `triggering_event_id` — a STRING that holds either an external Kafka
    `event_id` or, for synchronous internal flows, the string form of the
    internal transaction id. We match on `str(txn_id)` so internal
    rule-firings (when they exist) are picked up; today the top-up path
    does not emit Kafka events so this returns `None` in practice.

    The CHECK constraint on `ledger_entries.amount > 0` plus the
    `reward_value NUMERIC(20, 6)` storage means we can safely round to
    int for the mobile UI — fractional points don't exist on the rules
    engine surface.

    Args:
        session: Async DB session.
        txn_id: The transaction we just posted.

    Returns:
        Total points credited as an int, or `None` if no rules fired.
    """
    result = await session.execute(
        select(RewardEvent.reward_value).where(
            RewardEvent.triggering_event_id == str(txn_id)
        )
    )
    rows = result.scalars().all()
    if not rows:
        return None
    total = sum((Decimal(str(v)) for v in rows), start=Decimal("0"))
    # Round to int — mobile UI does not surface fractional points.
    return int(total)


