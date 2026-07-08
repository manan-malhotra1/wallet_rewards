"""Redemption service — provider registration, initiate, confirm, fail, callback.

Initiate follows the same overdraft pattern as P2P (Phase B):
    1. Lock user.points_account (SELECT FOR UPDATE)
    2. Derive available balance from the ledger
    3. Reject if available < amount (Pay-PRD-0740)
    4. Atomic two-legged PENDING ledger write (Pay-PRD-0670)
    5. INSERT redemptions row

Confirm flips the ledger entries PENDING -> COMPLETED (Pay-PRD-0690).
Fail flips them PENDING -> REVERSED (Pay-PRD-0700) — restoring the user's
available balance because REVERSED entries don't count in derive_balance.

Phase F.5 adds `process_provider_callback` — the HMAC-verified production
entrypoint. Confirm/fail remain as admin operator overrides.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hmac import verify_signature
from app.auth.principals import AdminPrincipal, UserPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import (
    record_audit_for_admin,
    record_audit_for_system,
    record_audit_for_user,
)
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
    SignatureNotConfigured,
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


async def _lock_account_for_update(session: AsyncSession, account_id: UUID) -> None:
    """Acquire a row-level write lock on the account until commit.

    Same pattern as `payments/service._lock_account_for_update`. Prevents
    concurrent redemptions from the same user wallet from both seeing the
    pre-debit balance.
    """
    await session.execute(select(Account.id).where(Account.id == account_id).with_for_update())


# -----------------------------------------------------------------------------
# Provider registration
# -----------------------------------------------------------------------------


async def register_provider(
    session: AsyncSession,
    request: ProviderRegistrationRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> RedemptionProvider:
    """Register a provider — auto-creates its provider_redemption_wallet.

    The wallet is in PTS (points), system-owned (user_id=NULL).

    Args:
        session: Async DB session.
        request: Validated registration payload.
        admin: Authenticated admin (audit context). Optional for internal callers.
        ip_address: Caller IP (audit context).

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
        shared_secret=request.shared_secret,
    )
    session.add(provider)
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session,
            admin,
            tenant_id=request.tenant_id,
            action="provider.registered",
            entity_type="redemption_provider",
            entity_id=str(provider.id),
            after_state={
                "name": provider.name,
                "max_retries": provider.max_retries,
                "shared_secret_configured": provider.shared_secret is not None,
            },
            ip_address=ip_address,
        )

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
    *,
    tenant_id: UUID,
    user_id: UUID,
    user: UserPrincipal | None = None,
    ip_address: str | None = None,
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
        tenant_id: From the session token via get_current_user (Phase F.4).
        user_id: From the session token via get_current_user (Phase F.4).
        request: Validated InitiateRedemptionRequest (body — provider + amount).
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
    await _assert_tenant_exists(session, tenant_id)

    # Pay-PRD-0260, Pay-PRD-0440/0450/0460: the user must hold an active role
    # permitting "redemption". Reject BEFORE any wallet lookup, lock, or
    # ledger write.
    await require_permission(session, user_id, "redemption")

    # Step-up PIN check — runs after role but before any DB lock or
    # ledger touch. No-op when no policy exists or when amount is below
    # the configured threshold.
    if user is not None:
        from app.modules.step_up.service import enforce_step_up

        await enforce_step_up(
            session,
            principal=user,
            transaction_type="redemption",
            currency="PTS",
            amount=request.points_amount,
            pin=request.pin,
            ip_address=ip_address,
        )

    provider = await _find_provider(session, request.provider_id, tenant_id)
    if provider.status != "active":
        raise RedemptionProviderInactive()

    user_points = await _find_user_points_account(session, tenant_id, user_id)

    # Idempotency fast-path: if a redemption with this key already exists in
    # this tenant, return it (no second ledger write).
    existing = (
        await session.execute(
            select(Redemption).where(
                Redemption.tenant_id == tenant_id,
                Redemption.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
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
            tenant_id=tenant_id,
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
            initiated_by=user_id,
            amount=request.points_amount,
        ),
    )

    redemption = Redemption(
        tenant_id=tenant_id,
        user_id=user_id,
        provider_id=provider.id,
        transaction_id=txn.id,
        points_amount=request.points_amount,
        status=REDEMPTION_STATUS_PENDING,
        idempotency_key=idempotency_key,
    )
    session.add(redemption)
    await session.flush()

    # NFR-0250: redemption initiation is a state change that must be audit-logged.
    # The user fixture may not be supplied (e.g. internal callers / seeds);
    # fall back to system actor when absent.
    if user is not None:
        record_audit_for_user(
            session,
            user,
            action="redemption.initiated",
            entity_type="redemption",
            entity_id=str(redemption.id),
            after_state={
                "status": redemption.status,
                "points_amount": str(redemption.points_amount),
                "provider_id": str(provider.id),
            },
            ip_address=ip_address,
        )
    else:
        record_audit_for_system(
            session,
            tenant_id=tenant_id,
            action="redemption.initiated",
            entity_type="redemption",
            entity_id=str(redemption.id),
            after_state={
                "status": redemption.status,
                "points_amount": str(redemption.points_amount),
                "provider_id": str(provider.id),
            },
        )

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


def _redemption_audit_snapshot(redemption: Redemption) -> dict:
    """Compact JSON-safe snapshot of the audit-relevant redemption fields."""
    return {
        "status": redemption.status,
        "retry_count": redemption.retry_count,
        "external_reference": redemption.external_reference,
        "failure_reason": redemption.failure_reason,
    }


async def _apply_completed_transition(
    session: AsyncSession, redemption: Redemption, external_reference: str | None
) -> None:
    """Flip a PENDING redemption + its ledger entries to COMPLETED.

    Caller is responsible for the commit so audit_log rows can land
    atomically with the state change.
    """
    # Per ledger-invariants.md §1, ledger_entries.status is the ONE field
    # that may change — flip via UPDATE on the parent transaction's entries.
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
    redemption.external_reference = external_reference
    redemption.completed_at = datetime.now(UTC)


async def _apply_failed_transition(
    session: AsyncSession, redemption: Redemption, reason: str
) -> None:
    """Flip a PENDING redemption + its ledger entries to FAILED/REVERSED.

    REVERSED ledger entries are excluded from `derive_balance`, so the
    user's available balance restores immediately.
    """
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
    redemption.failure_reason = reason


async def confirm_redemption(
    session: AsyncSession,
    redemption_id: UUID,
    request: ConfirmRedemptionRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Redemption:
    """Admin operator override — mark a PENDING redemption COMPLETED.

    Pay-PRD-0690. Phase F.5: HMAC-verified provider callbacks land via
    `process_provider_callback`; this endpoint is the manual escape hatch
    when the provider can't / hasn't called back.

    Args:
        session: Async DB session.
        redemption_id: UUID from the URL path.
        request: Carries tenant_id + optional external_reference.
        admin: Authenticated admin principal (for the audit_log entry).
        ip_address: Caller IP (audit context).

    Returns:
        The updated Redemption (status COMPLETED).

    Raises:
        RedemptionNotFound: 404.
        RedemptionNotPending: 409 — already terminal.
    """
    redemption = await _find_redemption_for_transition(session, redemption_id, request.tenant_id)
    before = _redemption_audit_snapshot(redemption)
    await _apply_completed_transition(session, redemption, request.external_reference)
    record_audit_for_admin(
        session,
        admin,
        tenant_id=redemption.tenant_id,
        action="redemption.confirmed.by_admin",
        entity_type="redemption",
        entity_id=str(redemption.id),
        before_state=before,
        after_state=_redemption_audit_snapshot(redemption),
        ip_address=ip_address,
        note="Operator override — provider callback bypassed.",
    )
    await session.commit()
    await session.refresh(redemption)
    return redemption


async def fail_redemption(
    session: AsyncSession,
    redemption_id: UUID,
    request: FailRedemptionRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> Redemption:
    """Admin operator override — mark a PENDING redemption FAILED.

    Pay-PRD-0700. Restores the user's points by REVERSING the PENDING
    ledger entries. Phase F.5 makes this an operator-only path; provider-
    initiated failures go through `process_provider_callback`.

    Args:
        session: Async DB session.
        redemption_id: UUID from the URL path.
        request: Carries tenant_id + reason.
        admin: Authenticated admin principal (for the audit_log entry).
        ip_address: Caller IP (audit context).

    Returns:
        The updated Redemption (status FAILED).
    """
    redemption = await _find_redemption_for_transition(session, redemption_id, request.tenant_id)
    before = _redemption_audit_snapshot(redemption)
    await _apply_failed_transition(session, redemption, request.reason)
    record_audit_for_admin(
        session,
        admin,
        tenant_id=redemption.tenant_id,
        action="redemption.failed.by_admin",
        entity_type="redemption",
        entity_id=str(redemption.id),
        before_state=before,
        after_state=_redemption_audit_snapshot(redemption),
        ip_address=ip_address,
        note=request.reason,
    )
    await session.commit()
    await session.refresh(redemption)
    return redemption


# -----------------------------------------------------------------------------
# Provider callback (Phase F.5)
# -----------------------------------------------------------------------------


async def process_provider_callback(
    session: AsyncSession,
    *,
    redemption_id: UUID,
    raw_body: bytes,
    signature_header: str,
    ip_address: str | None = None,
) -> Redemption:
    """HMAC-verified provider callback (Pay-PRD-0690 / 0700).

    Flow:
      1. Look up redemption by id (not tenant-scoped — we don't know tenant
         until after HMAC verifies).
      2. Look up provider → require `shared_secret` set.
      3. Verify HMAC against the raw body. On failure raise — exception
         handler returns 401.
      4. Parse the body INTO `ProviderCallbackRequest` (only after verify,
         so an attacker can't trigger 422 before the auth check).
      5. Reject if redemption already terminal (RedemptionNotPending → 409).
      6. Apply the requested transition; record audit_log entry; commit.

    Args:
        session: Async DB session.
        redemption_id: UUID from the URL path.
        raw_body: Raw bytes of the request body (BEFORE Pydantic parsing).
        signature_header: Value of the `X-Sasai-Signature` header.
        ip_address: Caller IP (audit context; usually a load balancer for
            server-to-server callbacks).

    Returns:
        The updated Redemption.

    Raises:
        RedemptionNotFound: 404 — unknown redemption_id.
        SignatureNotConfigured: 401 — provider has no shared_secret set.
        SignatureMissing/Malformed/TimestampSkew/Invalid: 401 — HMAC fails.
        RedemptionNotPending: 409 — redemption already terminal.
    """
    import json

    from app.modules.redemption.schemas import ProviderCallbackRequest

    redemption = (
        await session.execute(select(Redemption).where(Redemption.id == redemption_id))
    ).scalar_one_or_none()
    if redemption is None:
        raise RedemptionNotFound()

    provider = (
        await session.execute(
            select(RedemptionProvider).where(RedemptionProvider.id == redemption.provider_id)
        )
    ).scalar_one()

    if not provider.shared_secret:
        # Provider exists but isn't wired for HMAC callbacks; operators must
        # use the admin /confirm + /fail endpoints instead.
        raise SignatureNotConfigured()

    # Verify BEFORE doing any further work — fails loud on bad signature.
    # On failure: exception handler returns 401; no parsing leaks happen.
    verify_signature(
        header=signature_header,
        raw_body=raw_body,
        secret=provider.shared_secret,
    )

    # Parse + validate the body only after the signature passes.
    payload = json.loads(raw_body or b"{}")
    callback = ProviderCallbackRequest.model_validate(payload)

    # Status guard — already terminal redemptions are no-ops for replay safety.
    if redemption.status != REDEMPTION_STATUS_PENDING:
        raise RedemptionNotPending(redemption.status)

    before = _redemption_audit_snapshot(redemption)
    if callback.outcome == "completed":
        await _apply_completed_transition(session, redemption, callback.external_reference)
        action = "redemption.confirmed.by_provider"
        note = callback.external_reference
    else:
        # Default reason if the provider didn't send one — never blank to
        # keep the audit row queryable.
        await _apply_failed_transition(session, redemption, callback.reason or "provider_failed")
        action = "redemption.failed.by_provider"
        note = callback.reason

    record_audit_for_system(
        session,
        tenant_id=redemption.tenant_id,
        actor_id=f"provider:{provider.id}",
        action=action,
        entity_type="redemption",
        entity_id=str(redemption.id),
        before_state=before,
        after_state=_redemption_audit_snapshot(redemption),
        note=note,
    )
    # ip_address is intentionally not stored on the audit row for system
    # actors — provider callbacks come from server-to-server traffic where
    # the source IP is the load balancer, not the provider itself. Kept in
    # the signature for symmetry + future use.
    _ = ip_address

    await session.commit()
    await session.refresh(redemption)
    return redemption


# -----------------------------------------------------------------------------
# Lookups
# -----------------------------------------------------------------------------


async def get_redemption(session: AsyncSession, redemption_id: UUID, tenant_id: UUID) -> Redemption:
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
