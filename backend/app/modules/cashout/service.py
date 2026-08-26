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
from app.modules.commissions.resolution import resolve_earner_target
from app.modules.commissions.service import calculate_commission
from app.modules.identity.service import resolve_identifier
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    RewardTrigger,
    post_transaction,
)
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
from app.modules.rewards.outbox import issue_immediate_points
from app.modules.roles.service import require_permission
from app.modules.taxes.service import calculate_tax
from app.modules.user_types.service import get_user_type
from app.shared.exceptions import (
    AccountNotFound,
    CommissionWalletMissing,
    InsufficientFunds,
    RecipientNotAgent,
    SelfTransferNotAllowed,
    TenantNotFound,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    CATEGORY_RETAIL,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
    User,
)

CASH_OUT_SERVICE_CODE = "cashout"


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
    """Reject when the resolved cash-out recipient is not an agent-category type.

    A subscriber may only cash out TO an agent (the mirror of who is permitted
    to cash-in). Eligibility is read off the RETAIL CATEGORY of the recipient's
    type in the tenant's catalog, not off a hardcoded pair of codes: user types
    are runtime data now, and `retail` is precisely the category that means
    "agent-shaped tier" (`consumer` is the subscriber paying in, `business` is
    merchant collection). A tenant's own tiered-agent type is therefore eligible
    the moment it is created, with no second list to keep in step.

    A recipient whose type does not resolve at all is refused too, rather than
    treated as eligible — fail closed.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — a recipient in another tenant never resolves.
        user_id: The already-resolved recipient.

    Raises:
        RecipientNotAgent: 422 — the recipient's type is missing, unresolvable,
            or sits outside the Retail category.
    """
    result = await session.execute(
        select(User.user_type).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user_type = result.scalar_one_or_none()
    if user_type is None:
        raise RecipientNotAgent()
    # Retired types resolve here on purpose: an agent onboarded under a type the
    # operator has since retired must keep being able to take cash-outs, exactly
    # as `get_user_type` keeps existing users working (spec §11).
    type_row = await get_user_type(session, tenant_id, user_type)
    if type_row is None or type_row.category_code != CATEGORY_RETAIL:
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
) -> tuple[Transaction, UUID, int]:
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
        request.service_code: Optional derived service to transact under
            (spec §7). Omitted -> plain 'cashout', identical to pre-existing
            behaviour. When supplied, resolved ONCE up front and used for
            every downstream permission / pricing / limits / ledger step;
            `base_transaction_type` on the recorded transaction is always
            'cashout' regardless.

    Returns:
        (Transaction, agent_user_id, earned_points). `earned_points` is the
        points the withdrawing SUBSCRIBER earned from any reward rule that fired
        on this cash-out (0 outside `both` mode, no matching rule, or on replay).

    Raises:
        TenantNotFound / UserNotFound / AccountNotFound (404).
        NotAuthorised (403): the subscriber's role lacks the resolved service.
        RecipientNotAgent (422): the recipient is not an agent / super-agent.
        SelfTransferNotAllowed (422): subscriber tried to cash out to self.
        ServiceNotConfigured (422): pricing OR limit config for `cashout` is
            missing for the subscriber's user_type (invariant #12).
        InsufficientFunds (409): the subscriber's wallet can't cover the outflow.
    """
    await _assert_tenant_exists(session, tenant_id)

    # 0. Resolve the service code ONCE, before any permission/pricing/limits
    # gate, so every downstream step transacts under the SAME code (spec §7).
    # Omitted `service_code` resolves to CASH_OUT_SERVICE_CODE unchanged.
    from app.modules.services.service import assert_service_allowed, resolve_service_code
    from app.shared.utils.user_types import resolve_user_type

    subscriber_user_type = await resolve_user_type(session, tenant_id, subscriber_user_id)
    service_code = await resolve_service_code(
        session,
        tenant_id=tenant_id,
        base_code=CASH_OUT_SERVICE_CODE,
        requested_code=request.service_code,
        user_type=subscriber_user_type,
        channel="mobile",
    )

    # 1. Role — the subscriber must be permitted to the resolved service (Pay-PRD-0440/0450).
    await require_permission(session, subscriber_user_id, service_code)

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
        # Replay: the reward (if any) already fired on the original call, so no
        # new outbox row exists to drain — earned_points is 0 on the replay.
        return (
            existing,
            await _resolve_agent_from_txn(session, existing, subscriber_user_id),
            0,
        )

    # 1a. Admin access-lock (migration 0045). The SUBSCRIBER (initiator) must be
    # `active`; a txn_locked / suspended / closed subscriber is blocked here —
    # after the idempotency fast-path (a replay still returns the original txn)
    # and before any charge/ledger work. The agent is a passive recipient.
    from app.modules.identity.service import assert_user_can_transact

    await assert_user_can_transact(session, tenant_id=tenant_id, user_id=subscriber_user_id)

    # 1b. Per-service access policy (services.allowed_user_types / _channels).
    # Enforce that the acting subscriber's user_type + channel may initiate the
    # resolved service, mirroring the mobile display gate. After the
    # idempotency fast-path (replays still return the original txn) and before
    # any ledger work.
    await assert_service_allowed(
        session,
        tenant_id=tenant_id,
        transaction_type=service_code,
        user_type=subscriber_user_type,
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
        service=service_code,
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
        transaction_type=service_code,
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
        transaction_type=service_code,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    outcome = await calculate_commission(
        session,
        tenant_id=tenant_id,
        agent_user_id=agent_user_id,
        transaction_type=service_code,
        currency=currency,
        amount=request.amount,
    )
    tax = await calculate_tax(
        session,
        tenant_id=tenant_id,
        currency=currency,
        fee=fee_quote.fee,
        commission=outcome.self_amount,
        parent_commission=outcome.parent_amount,
    )

    # Where the earner's own commission lands (spec 2026-08-26, D6). Fails
    # CLOSED (§7.2): paying into the spendable wallet when the rule asked for a
    # commission wallet would silently void the review hold.
    earner_target = await resolve_earner_target(
        session,
        tenant_id=tenant_id,
        earner_user_id=agent_user_id,
        destination=outcome.destination,
        currency=currency,
    )
    if outcome.self_amount > 0 and earner_target.account_id is None:
        raise CommissionWalletMissing()
    commission_account_id = earner_target.account_id or agent_wallet.id

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
            agent_account_id=commission_account_id,
            parent_account_id=outcome.parent_account_id,
        ),
        ChargeAmounts(
            principal=request.amount,
            fee=fee_quote.fee,
            commission=outcome.self_amount,
            fee_tax=tax.fee_tax,
            commission_tax=tax.commission_tax,
            parent_commission=outcome.parent_amount,
            parent_commission_tax=tax.parent_commission_tax,
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
            transaction_type=service_code,
            # The BASE flow — always 'cashout' regardless of which derived
            # service (if any) was resolved above (spec §12.1).
            base_transaction_type=CASH_OUT_SERVICE_CODE,
            currency=currency,
            entries=assembled.entries,
            initiated_by=subscriber_user_id,
            amount=request.amount,
            fee_amount=assembled.fee_amount,
            commission_amount=assembled.commission_amount,
            parent_commission_amount=assembled.parent_commission_amount,
            tax_amount=assembled.tax_amount,
            # The reward recipient is the withdrawing SUBSCRIBER (the debited
            # wallet holder / initiator) — the receiving agent earns commission,
            # not rewards. In `both` mode this makes post_transaction write a
            # reward_outbox row for the subscriber atomically with the ledger
            # commit; other modes are a no-op.
            # transaction_type is the RESOLVED code (spec §8): a rule targeting
            # 'cashout' must not fire for a derived service — precise targeting
            # means a derived service needs its own rule.
            reward_trigger=RewardTrigger(
                user_id=subscriber_user_id,
                transaction_type=service_code,
                amount=request.amount,
                currency=currency,
            ),
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

    # Reward evaluation — post_transaction (and any audit commit above) have
    # already committed; in `both` mode that first commit also wrote a PENDING
    # reward_outbox row for the SUBSCRIBER. Drain it now in a FRESH session so
    # the reward work happens strictly AFTER the money commit, never inside the
    # ledger transaction (invariant #11). Fail-open — a reward hiccup is recorded
    # on the row for the recon sweep and never surfaces on the money path, so
    # earned_points just stays 0. No-op outside `both` mode (no outbox row).
    earned_points = await issue_immediate_points(
        session, tenant_id=tenant_id, user_id=subscriber_user_id
    )

    return txn, agent_user_id, earned_points


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
