"""Airtime recharge service — Epic 17.

Composition of two existing patterns:
  - the p2p orchestration (role -> limits -> step-up -> pricing -> overdraft ->
    reserve) from `payments.service.p2p_transfer`, and
  - the redemption reserve -> external -> status-flip lifecycle from
    `redemption.service`.

`initiate_recharge` reserves funds as a PENDING double-entry (DEBIT user wallet,
CREDIT the airtime merchant's holding account, + fee legs) and COMMITS.
`attempt_provision` then calls the provider AFTER the commit (NFR-0130): a fast
terminal result finalises the recharge in-request (feels synchronous); a
pending/slow result leaves it PENDING for the callback (S5) or reconciliation.
Finalisation flips the parent transaction + its ledger entries' status — never
an UPDATE to a ledger row's money (ledger-invariants.md §1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import UserPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.airtime.provider import (
    PROVIDER_OUTCOME_FAILED,
    PROVIDER_OUTCOME_SUCCESS,
    ProvisionRequest,
    get_provider,
)
from app.modules.airtime.schemas import AirtimeRechargeRequest
from app.modules.audit.service import record_audit_for_system, record_audit_for_user
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.roles.service import require_permission
from app.shared.exceptions import (
    AccountNotFound,
    AirtimeMerchantNotConfigured,
    AirtimeRechargeNotFound,
    InsufficientFunds,
    PricingConfigMissing,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    AIRTIME_STATUS_COMPLETED,
    AIRTIME_STATUS_PENDING,
    AIRTIME_STATUS_REVERSED,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_REVERSED,
    MERCHANT_PROFILE_STATUS_ACTIVE,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_PENDING,
    TXN_STATUS_REVERSED,
    Account,
    AirtimeRecharge,
    LedgerEntry,
    MerchantProfile,
    Tenant,
    Transaction,
)
from app.shared.utils.masking import mask_phone

# The airtime service code == Service.code == transaction_type — the single
# identifier pricing / limits / role permission / merchant lookup all key on.
AIRTIME_SERVICE_CODE = "airtime_recharge"


# -----------------------------------------------------------------------------
# Lookups
# -----------------------------------------------------------------------------


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _find_active_airtime_merchant(session: AsyncSession, tenant_id: UUID) -> MerchantProfile:
    """Return the tenant's single active airtime merchant, or raise.

    The `uq_merchant_profiles_active_service` partial-unique index guarantees at
    most one active merchant per (tenant, service_code), so this resolves the
    counterparty unambiguously.
    """
    result = await session.execute(
        select(MerchantProfile).where(
            MerchantProfile.tenant_id == tenant_id,
            MerchantProfile.service_code == AIRTIME_SERVICE_CODE,
            MerchantProfile.status == MERCHANT_PROFILE_STATUS_ACTIVE,
        )
    )
    merchant = result.scalar_one_or_none()
    if merchant is None:
        raise AirtimeMerchantNotConfigured()
    return merchant


async def _find_user_wallet(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, currency: str
) -> Account:
    """Return the buyer's financial wallet in `currency`, or raise."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.currency == currency,
        )
    )
    wallet = result.scalar_one_or_none()
    if wallet is None:
        raise AccountNotFound()
    return wallet


async def _get_or_create_merchant_holding(
    session: AsyncSession, tenant_id: UUID, merchant_user_id: UUID, currency: str
) -> Account:
    """Fetch-or-create the merchant's airtime_merchant_holding account (per currency).

    Mirrors `pricing.get_or_create_system_fee_account`, but merchant-owned
    (user_id set) rather than system-owned.
    """
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == merchant_user_id,
            Account.account_type == ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
            Account.currency == currency,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = Account(
            tenant_id=tenant_id,
            user_id=merchant_user_id,
            account_type=ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
            currency=currency,
        )
        session.add(account)
        await session.flush()
    return account


async def _lock_account_for_update(session: AsyncSession, account_id: UUID) -> None:
    """Row-lock an account until commit — serialises concurrent spends."""
    await session.execute(select(Account.id).where(Account.id == account_id).with_for_update())


# -----------------------------------------------------------------------------
# Initiate (reserve + commit)
# -----------------------------------------------------------------------------


async def initiate_recharge(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    user: UserPrincipal | None = None,
    ip_address: str | None = None,
    request: AirtimeRechargeRequest,
    idempotency_key: str,
) -> tuple[AirtimeRecharge, MerchantProfile]:
    """Reserve funds for a recharge and persist it PENDING (no provider call yet).

    Order matches `p2p_transfer` (Pay-PRD-0260): role -> limits -> step-up ->
    pricing -> overdraft -> reserve. The DEBIT (user wallet) / CREDIT (merchant
    holding) legs plus any fee legs are written PENDING in one atomic
    transaction, then committed so the provider call happens outside any DB
    transaction (NFR-0130).

    Idempotency: a replay with the same `(tenant, idempotency_key)` returns the
    existing recharge without a second ledger write.

    Returns:
        (recharge, merchant) — the merchant is passed on so `attempt_provision`
        can reach its provider config without re-querying.

    Raises:
        TenantNotFound / AirtimeMerchantNotConfigured / AccountNotFound (404/422).
        InsufficientFunds (409): available balance < amount + fee.
    """
    await _assert_tenant_exists(session, tenant_id)
    await require_permission(session, user_id, AIRTIME_SERVICE_CODE)

    merchant = await _find_active_airtime_merchant(session, tenant_id)

    # Idempotency fast-path — return the existing recharge before any write.
    existing = (
        await session.execute(
            select(AirtimeRecharge).where(
                AirtimeRecharge.tenant_id == tenant_id,
                AirtimeRecharge.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, merchant

    currency = request.currency.upper()
    wallet = await _find_user_wallet(session, tenant_id, user_id, currency)
    holding = await _get_or_create_merchant_holding(session, tenant_id, merchant.user_id, currency)

    await _lock_account_for_update(session, wallet.id)

    # Type-aware limits (resolve user_type internally), then step-up, then fee.
    from app.modules.limits.service import check_limits, check_wallet_send_limits

    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type=AIRTIME_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    await check_wallet_send_limits(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency, amount=request.amount
    )

    if user is not None:
        from app.modules.step_up.service import enforce_step_up

        await enforce_step_up(
            session,
            principal=user,
            transaction_type=AIRTIME_SERVICE_CODE,
            currency=currency,
            amount=request.amount,
            pin=request.pin,
            ip_address=ip_address,
        )

    fee = await _resolve_fee(session, tenant_id, user_id, currency, request.amount)

    # Overdraft check (Pay-PRD-0220) — must include the fee, before any write.
    balance, reserved = await derive_balance(session, wallet.id)
    if balance - reserved < request.amount + fee:
        raise InsufficientFunds()

    entries = [
        LedgerEntryRequest(account_id=wallet.id, entry_type=ENTRY_DEBIT, amount=request.amount),
        LedgerEntryRequest(account_id=holding.id, entry_type=ENTRY_CREDIT, amount=request.amount),
    ]
    if fee > 0:
        from app.modules.pricing.service import get_or_create_system_fee_account

        fee_account = await get_or_create_system_fee_account(
            session, tenant_id=tenant_id, currency=currency
        )
        entries.append(LedgerEntryRequest(account_id=wallet.id, entry_type=ENTRY_DEBIT, amount=fee))
        entries.append(
            LedgerEntryRequest(account_id=fee_account.id, entry_type=ENTRY_CREDIT, amount=fee)
        )

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type=AIRTIME_SERVICE_CODE,
            currency=currency,
            status=TXN_STATUS_PENDING,
            entries=entries,
            initiated_by=user_id,
            amount=request.amount,
            fee_amount=fee,
        ),
    )

    recharge = AirtimeRecharge(
        tenant_id=tenant_id,
        user_id=user_id,
        msisdn=request.msisdn,
        network=request.network,
        amount=request.amount,
        currency=currency,
        status=AIRTIME_STATUS_PENDING,
        transaction_id=txn.id,
        idempotency_key=idempotency_key,
    )
    session.add(recharge)
    await session.flush()

    # NFR-0250: initiation is a state change — audit it. msisdn is PII, so it is
    # masked in the audit trail (NFR-0240); amounts are not PII.
    audit_after = {
        "status": recharge.status,
        "amount": str(request.amount),
        "msisdn": mask_phone(request.msisdn),
        "merchant_user_id": str(merchant.user_id),
    }
    if user is not None:
        record_audit_for_user(
            session,
            user,
            action="airtime.recharge.initiated",
            entity_type="airtime_recharge",
            entity_id=str(recharge.id),
            after_state=audit_after,
            ip_address=ip_address,
        )
    else:
        record_audit_for_system(
            session,
            tenant_id=tenant_id,
            action="airtime.recharge.initiated",
            entity_type="airtime_recharge",
            entity_id=str(recharge.id),
            after_state=audit_after,
        )

    await session.commit()
    await session.refresh(recharge)
    return recharge, merchant


async def _resolve_fee(
    session: AsyncSession, tenant_id: UUID, user_id: UUID, currency: str, amount: Decimal
) -> Decimal:
    """Type-aware fee for the recharge; no pricing config => no fee (legacy)."""
    from app.modules.pricing.service import calculate_fee

    try:
        return await calculate_fee(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            transaction_type=AIRTIME_SERVICE_CODE,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=currency,
            amount=amount,
        )
    except PricingConfigMissing:
        return Decimal("0")


# -----------------------------------------------------------------------------
# Provider call (after commit) + finalize
# -----------------------------------------------------------------------------


async def _apply_completed(
    session: AsyncSession, recharge: AirtimeRecharge, provider_reference: str | None
) -> None:
    """Flip a PENDING recharge + its ledger entries to COMPLETED.

    Per ledger-invariants.md §1, ledger money is immutable — only the status
    flips, via the parent transaction's entries.
    """
    await session.execute(
        update(LedgerEntry)
        .where(LedgerEntry.transaction_id == recharge.transaction_id)
        .values(status=ENTRY_STATUS_COMPLETED)
    )
    await session.execute(
        update(Transaction)
        .where(Transaction.id == recharge.transaction_id)
        .values(status=TXN_STATUS_COMPLETED)
    )
    recharge.status = AIRTIME_STATUS_COMPLETED
    recharge.provider_reference = provider_reference
    recharge.completed_at = datetime.now(UTC)


async def _apply_reversed(
    session: AsyncSession, recharge: AirtimeRecharge, failure_reason: str
) -> None:
    """Flip a PENDING recharge + its ledger entries to REVERSED (refund).

    REVERSED entries are excluded from `derive_balance`, so the user's wallet —
    including any fee legs — is made whole immediately.
    """
    await session.execute(
        update(LedgerEntry)
        .where(LedgerEntry.transaction_id == recharge.transaction_id)
        .values(status=ENTRY_STATUS_REVERSED)
    )
    await session.execute(
        update(Transaction)
        .where(Transaction.id == recharge.transaction_id)
        .values(status=TXN_STATUS_REVERSED)
    )
    recharge.status = AIRTIME_STATUS_REVERSED
    recharge.failure_reason = failure_reason


def _audit_provider_transition(
    session: AsyncSession,
    recharge: AirtimeRecharge,
    merchant: MerchantProfile,
    action: str,
    note: str | None,
) -> None:
    """Write a system audit row for a provider-driven state change (NFR-0250)."""
    record_audit_for_system(
        session,
        tenant_id=recharge.tenant_id,
        actor_id=f"merchant:{merchant.user_id}",
        action=action,
        entity_type="airtime_recharge",
        entity_id=str(recharge.id),
        after_state={
            "status": recharge.status,
            "provider_reference": recharge.provider_reference,
        },
        note=note,
    )


async def attempt_provision(
    session: AsyncSession, recharge: AirtimeRecharge, merchant: MerchantProfile
) -> AirtimeRecharge:
    """Call the provider AFTER the reserve-commit and finalise the recharge.

    This is the "sync attempt" (Q2) whose timeout is the client's bounded wait
    (Q1). A terminal result finalises in-request; a pending result leaves the
    recharge PENDING for the callback / reconciliation. Idempotent: a recharge
    that is already terminal (e.g. an idempotent replay) is returned untouched.

    Side effects:
        On a terminal result, flips the ledger transaction + entries and writes
        a system audit row, then commits.
    """
    if recharge.status != AIRTIME_STATUS_PENDING:
        return recharge

    provider = get_provider(merchant.mode)
    result = await provider.provision(
        ProvisionRequest(
            recharge_id=str(recharge.id),
            msisdn=recharge.msisdn,
            network=recharge.network,
            amount=str(recharge.amount),
            currency=recharge.currency,
            provider_config=merchant.provider_config or {},
        )
    )

    if result.outcome == PROVIDER_OUTCOME_SUCCESS:
        await _apply_completed(session, recharge, result.provider_reference)
        _audit_provider_transition(
            session, recharge, merchant, "airtime.recharge.completed", result.provider_reference
        )
        await session.commit()
        await session.refresh(recharge)
    elif result.outcome == PROVIDER_OUTCOME_FAILED:
        await _apply_reversed(session, recharge, result.failure_reason or "provider_failed")
        _audit_provider_transition(
            session, recharge, merchant, "airtime.recharge.reversed", result.failure_reason
        )
        await session.commit()
        await session.refresh(recharge)
    # PENDING: leave the reservation in place; the callback / reconciliation
    # resolves it. The bounded client response returns 202 in this case.
    return recharge


async def purchase_airtime(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    user: UserPrincipal | None = None,
    ip_address: str | None = None,
    request: AirtimeRechargeRequest,
    idempotency_key: str,
) -> AirtimeRecharge:
    """Full recharge: reserve + commit, then the after-commit provider attempt."""
    recharge, merchant = await initiate_recharge(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        user=user,
        ip_address=ip_address,
        request=request,
        idempotency_key=idempotency_key,
    )
    return await attempt_provision(session, recharge, merchant)


# -----------------------------------------------------------------------------
# Lookup
# -----------------------------------------------------------------------------


async def get_recharge(
    session: AsyncSession, recharge_id: UUID, tenant_id: UUID
) -> AirtimeRecharge:
    """Tenant-scoped recharge lookup (poll endpoint)."""
    result = await session.execute(
        select(AirtimeRecharge).where(
            AirtimeRecharge.id == recharge_id,
            AirtimeRecharge.tenant_id == tenant_id,
        )
    )
    recharge = result.scalar_one_or_none()
    if recharge is None:
        raise AirtimeRechargeNotFound()
    return recharge
