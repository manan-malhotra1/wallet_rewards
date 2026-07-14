"""Agent cash-in service — Pricing v2 Epic 21 (Story 21.2).

An agent funds a customer's wallet from the agent's own e-float and earns a
platform-funded commission; the fee + tax are collected into the system wallets.

Order of operations (Pay-PRD-0260 shape): role -> resolve customer -> limits ->
step-up -> pricing (slab fee) -> commission -> tax -> assemble charges ->
advisory overdraft on the agent float -> post_transaction (which runs the
authoritative balance guard and commits).

`initiated_by` is the agent; the credited wallet is owned by the customer — the
ledger already treats actor != credited-owner as first-class (invariant #11's
recipient branch surfaces a detail-free error if the customer is over their cap).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_user
from app.modules.cashin.schemas import CashInRequest
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
    get_or_create_system_taxes,
    resolve_fee,
)
from app.modules.roles.service import require_permission
from app.modules.taxes.service import calculate_tax
from app.shared.exceptions import (
    AccountNotFound,
    InsufficientFunds,
    SelfTransferNotAllowed,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
)

CASH_IN_SERVICE_CODE = "cash_in"


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


def _net_debit(entries: list[LedgerEntryRequest], account_id: UUID) -> Decimal:
    """Net DEBIT (debits - credits) an account bears across the legs."""
    total = Decimal("0")
    for entry in entries:
        if entry.account_id != account_id:
            continue
        total += entry.amount if entry.entry_type == ENTRY_DEBIT else -entry.amount
    return total


async def cash_in(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_user_id: UUID,
    request: CashInRequest,
    idempotency_key: str,
    agent: UserPrincipal | None = None,
    ip_address: str | None = None,
) -> tuple[Transaction, UUID]:
    """Fund a customer's wallet from an agent's e-float, paying the agent a commission.

    Args:
        session: Async DB session (commits inside `post_transaction`).
        tenant_id: Tenant scope.
        agent_user_id: The acting agent (payer + commission beneficiary).
        request: The validated cash-in payload.
        idempotency_key: Unique per tenant; replays return the original txn.
        agent: The agent principal (for step-up + audit); None for internal calls.
        ip_address: Caller IP for the audit trail.

    Returns:
        (Transaction, customer_user_id).

    Raises:
        TenantNotFound / UserNotFound / AccountNotFound (404).
        NotAuthorised (403): the agent's role lacks `cash_in`.
        SelfTransferNotAllowed (422): agent tried to fund their own wallet.
        InsufficientFunds (409): the agent's float can't cover the outflow.
    """
    await _assert_tenant_exists(session, tenant_id)
    # 1. Role — the agent must be permitted to cash_in (Pay-PRD-0440/0450).
    await require_permission(session, agent_user_id, CASH_IN_SERVICE_CODE)

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
        return existing, await _resolve_customer_from_txn(session, existing, agent_user_id)

    # 2. Resolve the customer (tenant-scoped) and reject self cash-in.
    customer_row = await resolve_identifier(
        session, tenant_id, request.customer.identifier_type, request.customer.identifier_value
    )
    customer_user_id = customer_row.user_id
    if customer_user_id == agent_user_id:
        raise SelfTransferNotAllowed()

    currency = request.currency.upper()

    # Fail-closed service gate (Epic 23) — when the tenant requires config, BOTH
    # a pricing and a limit config must resolve for the acting agent's user_type
    # or the cash-in is rejected here (before any ledger work). No-op when the
    # flag is off. Runs after the idempotency fast-path so replays still return
    # the original transaction. cash_in already fails closed on missing pricing
    # via resolve_fee; the gate additionally closes the missing-limit gap and
    # yields a consistent ServiceNotConfigured error.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=CASH_IN_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        user_id=agent_user_id,
    )

    agent_wallet = await _find_user_wallet(
        session, tenant_id=tenant_id, user_id=agent_user_id, currency=currency
    )
    customer_wallet = await _find_user_wallet(
        session, tenant_id=tenant_id, user_id=customer_user_id, currency=currency
    )

    # 3. Limits on the agent (the one spending), then step-up.
    from app.modules.limits.service import check_limits, check_wallet_send_limits

    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=agent_user_id,
        transaction_type=CASH_IN_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    await check_wallet_send_limits(
        session,
        tenant_id=tenant_id,
        user_id=agent_user_id,
        currency=currency,
        amount=request.amount,
    )
    if agent is not None:
        from app.modules.step_up.service import enforce_step_up

        await enforce_step_up(
            session,
            principal=agent,
            transaction_type=CASH_IN_SERVICE_CODE,
            currency=currency,
            amount=request.amount,
            pin=request.pin,
            ip_address=ip_address,
        )

    # 4. Pricing (slab fee + inclusive flag), commission, tax.
    fee_quote = await resolve_fee(
        session,
        tenant_id=tenant_id,
        user_id=agent_user_id,
        transaction_type=CASH_IN_SERVICE_CODE,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    commission = await calculate_commission(
        session,
        tenant_id=tenant_id,
        agent_user_id=agent_user_id,
        transaction_type=CASH_IN_SERVICE_CODE,
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

    # 5. Resolve the system wallets and assemble the balanced legs.
    fee_account = await get_or_create_system_fee_account(
        session, tenant_id=tenant_id, currency=currency
    )
    commission_pool = await get_or_create_system_commission(
        session, tenant_id=tenant_id, currency=currency
    )
    taxes_account = await get_or_create_system_taxes(
        session, tenant_id=tenant_id, currency=currency
    )
    assembled = assemble_charges(
        ChargeAccounts(
            payer_account_id=agent_wallet.id,
            beneficiary_account_id=customer_wallet.id,
            fee_account_id=fee_account.id,
            taxes_account_id=taxes_account.id,
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

    # 6. Advisory overdraft on the agent float (net of the commission credit
    # that lands on the same wallet). The AUTHORITATIVE check is the balance
    # guard inside post_transaction; this just returns a clean 409 early.
    balance, reserved = await derive_balance(session, agent_wallet.id)
    if balance - reserved < _net_debit(assembled.entries, agent_wallet.id):
        raise InsufficientFunds()

    # 7. Post the balanced transaction. `skip_receive_cap` stays False so the
    # CUSTOMER's max_balance is still enforced (a genuine deposit); the agent's
    # commission credit is netted against their principal debit on the same
    # wallet, so it isn't independently cap-checked in normal operation.
    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type=CASH_IN_SERVICE_CODE,
            currency=currency,
            entries=assembled.entries,
            initiated_by=agent_user_id,
            amount=request.amount,
            fee_amount=assembled.fee_amount,
            commission_amount=assembled.commission_amount,
            tax_amount=assembled.tax_amount,
        ),
    )

    # NFR-0250: cash-in is a state change — audit it against the agent.
    if agent is not None:
        record_audit_for_user(
            session,
            agent,
            action="cash_in.completed",
            entity_type="transaction",
            entity_id=str(txn.id),
            after_state={
                "amount": str(request.amount),
                "currency": currency,
                "customer_user_id": str(customer_user_id),
                "fee": str(assembled.fee_amount),
                "commission": str(assembled.commission_amount),
                "tax": str(assembled.tax_amount),
                "status": txn.status,
            },
            ip_address=ip_address,
        )
        await session.commit()

    return txn, customer_user_id


async def _resolve_customer_from_txn(
    session: AsyncSession, txn: Transaction, agent_user_id: UUID
) -> UUID:
    """Find the funded customer for an idempotent replay.

    The transaction row doesn't store the customer separately, so we read the
    CREDIT leg landing on a `financial_wallet` owned by someone other than the
    agent — that is the funded customer. Falls back to the agent id only if no
    such leg is found (should not happen for a real cash-in).
    """
    result = await session.execute(
        select(Account.user_id)
        .join(LedgerEntry, LedgerEntry.account_id == Account.id)
        .where(
            LedgerEntry.transaction_id == txn.id,
            LedgerEntry.entry_type == ENTRY_CREDIT,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.user_id.is_not(None),
            Account.user_id != agent_user_id,
        )
        .limit(1)
    )
    customer_id = result.scalar_one_or_none()
    return customer_id if customer_id is not None else agent_user_id
