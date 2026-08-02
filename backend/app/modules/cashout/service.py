"""Subscriber cash-out service — the mirror of agent cash-in.

A subscriber (consumer) names an agent by an identifier and SENDS money to that
agent: the subscriber's financial wallet is DEBITED the principal (+ fee, which
the subscriber bears), the resolved agent's financial wallet is CREDITED the
principal, and the receiving agent earns a platform-funded commission; fee + tax
settle into the system wallets. Direction is exactly cash-in reversed, sharing
the same charge assembler so the inclusive/exclusive matrix stays single-sourced.

Order of operations (Pay-PRD-0260 shape): role -> resolve agent -> agent-type
guard -> fail-closed gate (invariant #12) -> limits -> step-up -> pricing (slab
fee) -> commission -> tax -> assemble charges -> advisory overdraft on the
subscriber wallet -> post_transaction (authoritative balance guard + commit).

`initiated_by` is the subscriber (the payer); the credited wallet is owned by
the agent — the ledger already treats actor != credited-owner as first-class.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_user
from app.modules.cashout.schemas import CashOutRequest
from app.modules.commissions.service import calculate_commission
from app.modules.identity.service import resolve_identifier
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.pricing.assembler import (
    ChargeAccounts,
    ChargeAmounts,
    ChargeFlags,
    assemble_charges,
)
from app.modules.pricing.service import (
    get_or_create_system_commission,
    get_or_create_system_fee_account,
    get_or_create_system_tax_commission,
    get_or_create_system_tax_service,
    resolve_fee,
)
from app.modules.roles.service import require_permission
from app.modules.taxes.service import calculate_tax
from app.shared.exceptions import (
    AccountNotFound,
    InsufficientFunds,
    RecipientNotAgent,
    SelfTransferNotAllowed,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    USER_TYPE_AGENT,
    USER_TYPE_SUPER_AGENT,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
    User,
)

CASH_OUT_SERVICE_CODE = "cashout"

# The user types eligible to RECEIVE a cash-out (mirror of who may cash-in).
_AGENT_USER_TYPES = (USER_TYPE_AGENT, USER_TYPE_SUPER_AGENT)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject if the tenant_id is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


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


async def _assert_recipient_is_agent(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> None:
    """Reject when the resolved cash-out recipient is not an agent.

    A subscriber may only cash out TO an agent / super-agent (the mirror of who
    is permitted to cash-in). A non-agent recipient is a 422 `recipient_not_agent`.
    """
    result = await session.execute(
        select(User.user_type).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user_type = result.scalar_one_or_none()
    if user_type not in _AGENT_USER_TYPES:
        raise RecipientNotAgent()


def _net_debit(entries: list[LedgerEntryRequest], account_id: UUID) -> Decimal:
    """Net DEBIT (debits - credits) an account bears across the legs."""
    total = Decimal("0")
    for entry in entries:
        if entry.account_id != account_id:
            continue
        total += entry.amount if entry.entry_type == ENTRY_DEBIT else -entry.amount
    return total


async def cash_out(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    subscriber_user_id: UUID,
    request: CashOutRequest,
    idempotency_key: str,
    subscriber: UserPrincipal | None = None,
    ip_address: str | None = None,
) -> tuple[Transaction, UUID]:
    """Send money from a subscriber's wallet to an agent (mirror of cash-in).

    Args:
        session: Async DB session (commits inside `post_transaction`).
        tenant_id: Tenant scope.
        subscriber_user_id: The acting subscriber (the payer / spender).
        request: The validated cash-out payload (names the agent recipient).
        idempotency_key: Unique per tenant; replays return the original txn.
        subscriber: The subscriber principal (for step-up + audit); None for
            internal calls.
        ip_address: Caller IP for the audit trail.

    Returns:
        (Transaction, agent_user_id).

    Raises:
        TenantNotFound / UserNotFound / AccountNotFound (404).
        NotAuthorised (403): the subscriber's role lacks `cashout`.
        RecipientNotAgent (422): the recipient is not an agent / super-agent.
        SelfTransferNotAllowed (422): subscriber tried to cash out to self.
        ServiceNotConfigured (422): pricing OR limit config for `cashout` is
            missing for the subscriber's user_type (invariant #12).
        InsufficientFunds (409): the subscriber's wallet can't cover the outflow.
    """
    await _assert_tenant_exists(session, tenant_id)
    # 1. Role — the subscriber must be permitted to cash_out (Pay-PRD-0440/0450).
    await require_permission(session, subscriber_user_id, CASH_OUT_SERVICE_CODE)

    # Idempotency fast-path — return the existing transaction before any work.
    existing = (
        await session.execute(
            select(Transaction).where(
                Transaction.tenant_id == tenant_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, await _resolve_agent_from_txn(session, existing, subscriber_user_id)

    # 1a. Admin access-lock (migration 0045). The SUBSCRIBER (initiator) must be
    # `active`; a txn_locked / suspended / closed subscriber is blocked here —
    # after the idempotency fast-path (a replay still returns the original txn)
    # and before any charge/ledger work. The agent is a passive recipient.
    from app.modules.identity.service import assert_user_can_transact

    await assert_user_can_transact(session, tenant_id=tenant_id, user_id=subscriber_user_id)

    # 1b. Per-service access policy (services.allowed_user_types / _channels).
    # Enforce that the acting subscriber's user_type + channel may initiate
    # cashout, mirroring the mobile display gate. After the idempotency fast-path
    # (replays still return the original txn) and before any ledger work.
    from app.modules.services.service import assert_service_allowed
    from app.shared.utils.user_types import resolve_user_type

    await assert_service_allowed(
        session,
        tenant_id=tenant_id,
        transaction_type=CASH_OUT_SERVICE_CODE,
        user_type=await resolve_user_type(session, tenant_id, subscriber_user_id),
        channel="mobile",
    )

    # 2. Resolve the agent recipient (tenant-scoped), reject self, enforce type.
    agent_row = await resolve_identifier(
        session, tenant_id, request.identifier_type, request.identifier_value
    )
    agent_user_id = agent_row.user_id
    if agent_user_id == subscriber_user_id:
        raise SelfTransferNotAllowed()
    await _assert_recipient_is_agent(session, tenant_id=tenant_id, user_id=agent_user_id)

    currency = request.currency.upper()

    # 3. Fail-closed service gate (invariant #12, Epic 23). UNCONDITIONAL: BOTH a
    # pricing AND a limit config must resolve for the acting SUBSCRIBER's
    # user_type or the cash-out is rejected here, before any ledger work. Runs
    # after the idempotency fast-path so replays still return the original txn.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=CASH_OUT_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        user_id=subscriber_user_id,
    )

    subscriber_wallet = await _find_user_wallet(
        session, tenant_id=tenant_id, user_id=subscriber_user_id, currency=currency
    )
    agent_wallet = await _find_user_wallet(
        session, tenant_id=tenant_id, user_id=agent_user_id, currency=currency
    )

    # 4. Limits on the subscriber (the one spending), then step-up.
    from app.modules.limits.service import check_limits, check_wallet_send_limits

    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=subscriber_user_id,
        transaction_type=CASH_OUT_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    await check_wallet_send_limits(
        session,
        tenant_id=tenant_id,
        user_id=subscriber_user_id,
        currency=currency,
        amount=request.amount,
    )
    if subscriber is not None:
        from app.modules.step_up.service import enforce_step_up

        await enforce_step_up(
            session,
            principal=subscriber,
            transaction_type=CASH_OUT_SERVICE_CODE,
            currency=currency,
            amount=request.amount,
            pin=request.pin,
            ip_address=ip_address,
        )

    # 5. Pricing (slab fee + inclusive flag) for the SUBSCRIBER, commission for
    # the receiving AGENT, tax on both. The subscriber bears the fee; the agent
    # earns the commission (its config is keyed on the agent's user_type).
    fee_quote = await resolve_fee(
        session,
        tenant_id=tenant_id,
        user_id=subscriber_user_id,
        transaction_type=CASH_OUT_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    commission = await calculate_commission(
        session,
        tenant_id=tenant_id,
        agent_user_id=agent_user_id,
        transaction_type=CASH_OUT_SERVICE_CODE,
        currency=currency,
        amount=request.amount,
    )
    tax = await calculate_tax(
        session,
        tenant_id=tenant_id,
        currency=currency,
        fee=fee_quote.fee,
        commission=commission,
    )

    # 6. Resolve the system wallets and assemble the balanced legs. Direction is
    # cash-in reversed: the SUBSCRIBER is the payer, the AGENT the beneficiary
    # (and the commission beneficiary).
    fee_account = await get_or_create_system_fee_account(
        session, tenant_id=tenant_id, currency=currency
    )
    commission_pool = await get_or_create_system_commission(
        session, tenant_id=tenant_id, currency=currency
    )
    service_tax_account = await get_or_create_system_tax_service(
        session, tenant_id=tenant_id, currency=currency
    )
    commission_tax_account = await get_or_create_system_tax_commission(
        session, tenant_id=tenant_id, currency=currency
    )
    assembled = assemble_charges(
        ChargeAccounts(
            payer_account_id=subscriber_wallet.id,
            beneficiary_account_id=agent_wallet.id,
            fee_account_id=fee_account.id,
            service_tax_account_id=service_tax_account.id,
            commission_tax_account_id=commission_tax_account.id,
            commission_pool_account_id=commission_pool.id,
            agent_account_id=agent_wallet.id,  # commission lands on the agent's float
        ),
        ChargeAmounts(
            principal=request.amount,
            fee=fee_quote.fee,
            commission=commission,
            fee_tax=tax.fee_tax,
            commission_tax=tax.commission_tax,
        ),
        ChargeFlags(
            fee_inclusive=fee_quote.fee_inclusive,
            fee_tax_inclusive=tax.fee_tax_inclusive,
            commission_tax_inclusive=tax.commission_tax_inclusive,
        ),
    )

    # 7. Advisory overdraft on the subscriber wallet (net of any leg landing back
    # on it). The AUTHORITATIVE check is the balance guard inside
    # post_transaction (invariant #11); this just returns a clean 409 early.
    balance, reserved = await derive_balance(session, subscriber_wallet.id)
    if balance - reserved < _net_debit(assembled.entries, subscriber_wallet.id):
        raise InsufficientFunds()

    # 8. Post the balanced transaction through the single money choke point.
    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type=CASH_OUT_SERVICE_CODE,
            currency=currency,
            entries=assembled.entries,
            initiated_by=subscriber_user_id,
            amount=request.amount,
            fee_amount=assembled.fee_amount,
            commission_amount=assembled.commission_amount,
            tax_amount=assembled.tax_amount,
        ),
    )

    # NFR-0250: cash-out is a state change — audit it against the subscriber.
    if subscriber is not None:
        record_audit_for_user(
            session,
            subscriber,
            action="cashout.completed",
            entity_type="transaction",
            entity_id=str(txn.id),
            after_state={
                "amount": str(request.amount),
                "currency": currency,
                "agent_user_id": str(agent_user_id),
                "fee": str(assembled.fee_amount),
                "commission": str(assembled.commission_amount),
                "tax": str(assembled.tax_amount),
                "status": txn.status,
            },
            ip_address=ip_address,
        )
        await session.commit()

    return txn, agent_user_id


async def _resolve_agent_from_txn(
    session: AsyncSession, txn: Transaction, subscriber_user_id: UUID
) -> UUID:
    """Find the receiving agent for an idempotent replay.

    The transaction row doesn't store the agent separately, so we read the
    CREDIT leg landing on a `financial_wallet` owned by someone other than the
    subscriber — that is the receiving agent. Falls back to the subscriber id
    only if no such leg is found (should not happen for a real cash-out).
    """
    result = await session.execute(
        select(Account.user_id)
        .join(LedgerEntry, LedgerEntry.account_id == Account.id)
        .where(
            LedgerEntry.transaction_id == txn.id,
            LedgerEntry.entry_type == ENTRY_CREDIT,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.user_id.is_not(None),
            Account.user_id != subscriber_user_id,
        )
        .limit(1)
    )
    agent_id = result.scalar_one_or_none()
    return agent_id if agent_id is not None else subscriber_user_id
