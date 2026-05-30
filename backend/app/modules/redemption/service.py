"""Redemption service — provider registration, initiate, confirm, fail.

Initiate follows the same overdraft pattern as P2P (Phase B):
    1. Lock user.points_account (SELECT FOR UPDATE)
    2. Derive available balance from the ledger
    3. Reject if available < amount (Pay-PRD-0740)
    4. Atomic two-legged PENDING ledger write (Pay-PRD-0670)
    5. INSERT redemptions row

Confirm flips the ledger entries PENDING -> COMPLETED (Pay-PRD-0690).
Fail flips them PENDING -> REVERSED (Pay-PRD-0700) — restoring the user's
available balance because REVERSED entries don't count in derive_balance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.redemption.schemas import (
    ConfirmRedemptionRequest,
    FailRedemptionRequest,
    InitiateRedemptionRequest,
    ProviderRegistrationRequest,
)
from app.modules.roles.service import require_permission
from app.shared.exceptions import (
    InsufficientFunds,
    RedemptionNotFound,
    RedemptionNotPending,
    RedemptionProviderInactive,
    RedemptionProviderNotFound,
    TenantNotFound,
    UserPointsAccountMissing,
)
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_PROVIDER_REDEMPTION,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    ENTRY_STATUS_REVERSED,
    REDEMPTION_STATUS_COMPLETED,
    REDEMPTION_STATUS_FAILED,
    REDEMPTION_STATUS_PENDING,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_PENDING,
    TXN_STATUS_REVERSED,
    Account,
    LedgerEntry,
    Redemption,
    RedemptionProvider,
    Tenant,
    Transaction,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_user_points_account(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> Account:
    """Return the user's points_account in this tenant, or raise."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_POINTS,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise UserPointsAccountMissing()
    return account


async def _lock_account_for_update(
    session: AsyncSession, account_id: UUID
) -> None:
    """Acquire a row-level write lock on the account until commit.

    Same pattern as `payments/service._lock_account_for_update`. Prevents
    concurrent redemptions from the same user wallet from both seeing the
    pre-debit balance.
    """
    await session.execute(
        select(Account.id).where(Account.id == account_id).with_for_update()
    )


# -----------------------------------------------------------------------------
# Provider registration
# -----------------------------------------------------------------------------


async def register_provider(
    session: AsyncSession, request: ProviderRegistrationRequest
) -> RedemptionProvider:
    """Register a provider — auto-creates its provider_redemption_wallet.

    The wallet is in PTS (points), system-owned (user_id=NULL).

    Args:
        session: Async DB session.
        request: Validated registration payload.

    Returns:
        The persisted RedemptionProvider with `redemption_wallet_account_id`
        set to the auto-created wallet.

    Raises:
        TenantNotFound: 404 when tenant_id is unknown.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    # Step 1: create the provider's redemption wallet (system-owned).
    wallet = Account(
        tenant_id=request.tenant_id,
        account_type=ACCOUNT_TYPE_PROVIDER_REDEMPTION,
        currency="PTS",
    )
    session.add(wallet)
    await session.flush()  # populate wallet.id

    # Step 2: create the provider row, linking the wallet.
    provider = RedemptionProvider(
        tenant_id=request.tenant_id,
        name=request.name,
        redemption_wallet_account_id=wallet.id,
        status_check_url=request.status_check_url,
        max_retries=request.max_retries,
        retry_interval_secs=request.retry_interval_secs,
        escalate_after_mins=request.escalate_after_mins,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


async def _find_provider(
    session: AsyncSession, provider_id: UUID, tenant_id: UUID
) -> RedemptionProvider:
    """Tenant-scoped provider lookup — never leaks across tenants."""
    result = await session.execute(
        select(RedemptionProvider).where(
            RedemptionProvider.id == provider_id,
            RedemptionProvider.tenant_id == tenant_id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise RedemptionProviderNotFound()
    return provider


# -----------------------------------------------------------------------------
# Initiate
# -----------------------------------------------------------------------------


async def initiate_redemption(
    session: AsyncSession,
    request: InitiateRedemptionRequest,
    idempotency_key: str,
) -> Redemption:
    """Initiate a redemption — Pay-PRD-0660 to 0670, 0740.

    Steps (matches Phase D threat model §2):
      1. Validate tenant exists.
      2. Find provider (tenant-scoped, must be active).
      3. Find user's points_account.
      4. Lock the points_account for the duration of the DB transaction.
      5. Derive balance, reject if available < amount (Pay-PRD-0740).
      6. Atomic two-legged PENDING ledger write (Pay-PRD-0670).
      7. INSERT redemptions row with status=PENDING.

    Idempotency: the underlying ledger transaction uses `idempotency_key` as
    its key. Replays return the existing transaction; we then return the
    existing redemption row (matching by `(tenant_id, idempotency_key)`).

    Args:
        session: Async DB session.
        request: Validated InitiateRedemptionRequest.
        idempotency_key: Client-supplied unique key (Pay-PRD-0200).

    Returns:
        The persisted Redemption (PENDING, or existing on replay).

    Raises:
        TenantNotFound: unknown tenant.
        RedemptionProviderNotFound: 404 — provider missing in tenant.
        RedemptionProviderInactive: 409 — provider exists but is inactive.
        UserPointsAccountMissing: 422 — user has no points_account.
        InsufficientFunds: 409 — available balance < points_amount.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    # Step 1 (Pay-PRD-0260, Pay-PRD-0440/0450/0460): the user must hold an
    # active role permitting "redemption". Reject BEFORE any wallet lookup,
    # lock, or ledger write.
    await require_permission(session, request.user_id, "redemption")

    provider = await _find_provider(session, request.provider_id, request.tenant_id)
    if provider.status != "active":
        raise RedemptionProviderInactive()

    user_points = await _find_user_points_account(
        session, request.tenant_id, request.user_id
    )

    # Idempotency fast-path: if a redemption with this key already exists in
    # this tenant, return it (no second ledger write).
    existing = (await session.execute(
        select(Redemption).where(
            Redemption.tenant_id == request.tenant_id,
            Redemption.idempotency_key == idempotency_key,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing

    # Lock the user's points_account so concurrent redemptions serialise.
    await _lock_account_for_update(session, user_points.id)

    # Derive balance UNDER LOCK — never from the snapshot table.
    balance, reserved = await derive_balance(session, user_points.id)
    available = balance - reserved
    if available < request.points_amount:
        raise InsufficientFunds()

    # Atomic two-legged PENDING write (Pay-PRD-0670). The ledger service
    # handles idempotency on the same key in case of a write race.
    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=request.tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="redemption",
            currency=user_points.currency,
            status=TXN_STATUS_PENDING,
            entries=[
                LedgerEntryRequest(
                    account_id=user_points.id,
                    entry_type=ENTRY_DEBIT,
                    amount=request.points_amount,
                ),
                LedgerEntryRequest(
                    account_id=provider.redemption_wallet_account_id,
                    entry_type=ENTRY_CREDIT,
                    amount=request.points_amount,
                ),
            ],
            initiated_by=request.user_id,
            amount=request.points_amount,
        ),
    )

    redemption = Redemption(
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        provider_id=provider.id,
        transaction_id=txn.id,
        points_amount=request.points_amount,
        status=REDEMPTION_STATUS_PENDING,
        idempotency_key=idempotency_key,
    )
    session.add(redemption)
    await session.commit()
    await session.refresh(redemption)
    return redemption


# -----------------------------------------------------------------------------
# Confirm / Fail
# -----------------------------------------------------------------------------


async def _find_redemption_for_transition(
    session: AsyncSession, redemption_id: UUID, tenant_id: UUID
) -> Redemption:
    """Find a redemption in this tenant; reject if not PENDING (terminal)."""
    result = await session.execute(
        select(Redemption).where(
            Redemption.id == redemption_id,
            Redemption.tenant_id == tenant_id,
        )
    )
    redemption = result.scalar_one_or_none()
    if redemption is None:
        raise RedemptionNotFound()
    if redemption.status != REDEMPTION_STATUS_PENDING:
        raise RedemptionNotPending(redemption.status)
    return redemption


async def confirm_redemption(
    session: AsyncSession,
    redemption_id: UUID,
    request: ConfirmRedemptionRequest,
) -> Redemption:
    """Mark a PENDING redemption COMPLETED (Pay-PRD-0690).

    Flips the two ledger entries from PENDING to COMPLETED, the transaction
    from PENDING to COMPLETED, and the redemption row to COMPLETED.

    Args:
        session: Async DB session.
        redemption_id: UUID from the URL path.
        request: Carries tenant_id + optional external_reference.

    Returns:
        The updated Redemption (status COMPLETED).

    Raises:
        RedemptionNotFound: 404.
        RedemptionNotPending: 409 — already terminal.
    """
    redemption = await _find_redemption_for_transition(
        session, redemption_id, request.tenant_id
    )

    # Flip ledger entries PENDING -> COMPLETED. The status field on
    # ledger_entries is the ONE thing that may change (see ledger-invariants.md).
    await session.execute(
        update(LedgerEntry)
        .where(LedgerEntry.transaction_id == redemption.transaction_id)
        .values(status=ENTRY_STATUS_COMPLETED)
    )
    await session.execute(
        update(Transaction)
        .where(Transaction.id == redemption.transaction_id)
        .values(status=TXN_STATUS_COMPLETED)
    )

    redemption.status = REDEMPTION_STATUS_COMPLETED
    redemption.external_reference = request.external_reference
    redemption.completed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(redemption)
    return redemption


async def fail_redemption(
    session: AsyncSession,
    redemption_id: UUID,
    request: FailRedemptionRequest,
) -> Redemption:
    """Mark a PENDING redemption FAILED (Pay-PRD-0700) — restores user points.

    Flips the two ledger entries from PENDING to REVERSED. REVERSED entries
    are excluded from `derive_balance`, so the user's available balance
    is restored immediately.

    Args:
        session: Async DB session.
        redemption_id: UUID from the URL path.
        request: Carries tenant_id + reason.

    Returns:
        The updated Redemption (status FAILED).
    """
    redemption = await _find_redemption_for_transition(
        session, redemption_id, request.tenant_id
    )

    await session.execute(
        update(LedgerEntry)
        .where(LedgerEntry.transaction_id == redemption.transaction_id)
        .values(status=ENTRY_STATUS_REVERSED)
    )
    await session.execute(
        update(Transaction)
        .where(Transaction.id == redemption.transaction_id)
        .values(status=TXN_STATUS_REVERSED)
    )

    redemption.status = REDEMPTION_STATUS_FAILED
    redemption.failure_reason = request.reason
    await session.commit()
    await session.refresh(redemption)
    return redemption


# -----------------------------------------------------------------------------
# Lookups
# -----------------------------------------------------------------------------


async def get_redemption(
    session: AsyncSession, redemption_id: UUID, tenant_id: UUID
) -> Redemption:
    """Tenant-scoped redemption lookup."""
    result = await session.execute(
        select(Redemption).where(
            Redemption.id == redemption_id,
            Redemption.tenant_id == tenant_id,
        )
    )
    redemption = result.scalar_one_or_none()
    if redemption is None:
        raise RedemptionNotFound()
    return redemption


# Suppress unused-import warnings for symbols we don't reference directly
# but import for callers / clarity.
_ = (uuid4, ENTRY_STATUS_PENDING)
