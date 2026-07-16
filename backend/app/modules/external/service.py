"""External partner fund / withdraw (Epic 18 S2).

Money movement initiated by a partner over the API-key + HMAC surface, reusing
the treasury money core. Differences from the operator (admin) path:
  - the partner's ``Idempotency-Key`` is the ledger transaction key, so a
    network retry returns the original result instead of double-moving money;
  - type-aware limits are enforced (a partner is less trusted than an operator);
  - the audit actor is the API key (``apikey:<key_id>``), not an admin.

The tenant always comes from the key (``principal.tenant_id``), never the body,
and the target is always a user's financial_wallet — never a system wallet.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import ApiKeyPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_system
from app.modules.external.schemas import ExternalFundRequest, ExternalWithdrawRequest
from app.modules.limits.service import check_limits, check_wallet_send_limits
from app.modules.payments.service import fund
from app.modules.treasury.schemas import FundUserResponse, WithdrawFromUserResponse
from app.modules.treasury.service import (
    get_or_create_operator_adjustment,
    post_user_withdraw,
    resolve_user_financial_wallet,
    resolve_withdraw_amount,
)
from app.shared.exceptions import DuplicateIdempotencyKey
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Transaction


async def _find_by_idempotency(
    session: AsyncSession, tenant_id: UUID, idempotency_key: str
) -> Transaction | None:
    """Return the transaction already posted under this key, or None.

    The idempotency fast-path MUST run before limits — a retry would otherwise
    have its first (committed) move counted in the rolling caps and be wrongly
    rejected.
    """
    return (
        await session.execute(
            select(Transaction).where(
                Transaction.tenant_id == tenant_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


async def external_fund(
    session: AsyncSession,
    *,
    principal: ApiKeyPrincipal,
    request: ExternalFundRequest,
    idempotency_key: str,
) -> FundUserResponse:
    """Credit a user's wallet on behalf of a partner (reuses `fund`).

    Raises:
        UserNotFound (404): identifier doesn't resolve in the key's tenant.
        AccountNotFound (404): the user has no financial_wallet for the currency.
    """
    tenant_id = principal.tenant_id
    currency = request.currency.upper()
    user_id, wallet = await resolve_user_financial_wallet(
        session, tenant_id, request.identifier_type, request.identifier_value, currency
    )

    existing = await _find_by_idempotency(session, tenant_id, idempotency_key)
    if existing is not None:
        # Bind the key to the operation: a key reused for a different op (or a
        # conflicting body) must not silently return a mismatched txn (S4 M-03).
        if existing.transaction_type != "fund":
            raise DuplicateIdempotencyKey()
        balance, _ = await derive_balance(session, wallet.id)
        return FundUserResponse(
            transaction_id=existing.id,
            user_id=user_id,
            amount=Decimal(str(existing.amount)),
            currency=str(existing.currency),
            new_balance=balance,
        )

    # Fail-closed service gate (invariant #12). Runs AFTER the idempotency
    # fast-path (a replay of an already-posted fund must still return the
    # original result) but BEFORE any ledger work: BOTH a pricing and a limit
    # config must resolve for the target user's type or the fund is rejected
    # 422 here. Unconditional — no tenant flag, no silent zero-fee fall-through.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service="fund",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        user_id=user_id,
    )

    # No explicit wallet lock here: `fund` funnels through `post_transaction`,
    # whose balance guard (invariant #11) locks the wallet FOR UPDATE and enforces
    # `max_balance` under that lock — the single authoritative check. Two
    # concurrent funds serialise there, so neither can race past the cap.

    # Per-transaction cap. Rolling `fund` caps don't aggregate (fund is
    # system-initiated, initiated_by=NULL); fund's own wallet-receive cap is
    # the effective cumulative inflow guard.
    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type="fund",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    txn = await fund(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        amount=request.amount,
        currency=currency,
        idempotency_key=idempotency_key,
    )
    record_audit_for_system(
        session,
        tenant_id=tenant_id,
        actor_id=f"apikey:{principal.key_id}",
        action="external.fund",
        entity_type="user",
        entity_id=str(user_id),
        after_state={
            "amount": str(request.amount),
            "currency": currency,
            "transaction_id": str(txn.id),
            "reason": request.reason,
        },
    )
    await session.commit()
    balance, _ = await derive_balance(session, wallet.id)
    return FundUserResponse(
        transaction_id=txn.id,
        user_id=user_id,
        amount=request.amount,
        currency=currency,
        new_balance=balance,
    )


async def external_withdraw(
    session: AsyncSession,
    *,
    principal: ApiKeyPrincipal,
    request: ExternalWithdrawRequest,
    idempotency_key: str,
) -> WithdrawFromUserResponse:
    """Debit a user's wallet on behalf of a partner (reuses the treasury core).

    `withdraw_all` pulls the full available balance. Type-aware `withdraw` +
    wallet-send caps are enforced on the resolved amount.

    Raises:
        UserNotFound / AccountNotFound (404); NothingToWithdraw (409);
        InsufficientFunds (409); AmountAboveMax etc. (422/429) when a limit trips.
    """
    tenant_id = principal.tenant_id
    currency = request.currency.upper()
    user_id, wallet = await resolve_user_financial_wallet(
        session, tenant_id, request.identifier_type, request.identifier_value, currency
    )

    existing = await _find_by_idempotency(session, tenant_id, idempotency_key)
    if existing is not None:
        # Bind the key to the operation (S4 M-03).
        if existing.transaction_type != "withdraw":
            raise DuplicateIdempotencyKey()
        balance, _ = await derive_balance(session, wallet.id)
        return WithdrawFromUserResponse(
            transaction_id=existing.id,
            user_id=user_id,
            amount=Decimal(str(existing.amount)),
            currency=str(existing.currency),
            new_balance=balance,
        )

    # Fail-closed service gate (invariant #12). AFTER the idempotency fast-path,
    # BEFORE any ledger work: BOTH a pricing and a limit config must resolve for
    # the target user's type or the withdraw is rejected 422 here. Unconditional.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service="withdraw",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        user_id=user_id,
    )

    # Resolve the counter account up front so it exists before `post_user_withdraw`
    # posts the balanced legs. No explicit wallet lock here: `post_transaction`'s
    # balance guard (invariant #11) locks the wallet FOR UPDATE and runs the
    # overdraft check under it, held through the debit commit — so two concurrent
    # distinct-key withdraws serialise there and neither can drive the balance
    # negative. `resolve_withdraw_amount` below is an advisory early error only.
    operator_adjustment = await get_or_create_operator_adjustment(
        session, tenant_id=tenant_id, currency=currency
    )
    final_amount = await resolve_withdraw_amount(
        session, wallet, amount=request.amount, withdraw_all=request.withdraw_all
    )
    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type="withdraw",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=final_amount,
    )
    await check_wallet_send_limits(
        session, tenant_id=tenant_id, user_id=user_id, currency=currency, amount=final_amount
    )
    txn = await post_user_withdraw(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        wallet=wallet,
        operator_adjustment=operator_adjustment,
        amount=final_amount,
        currency=currency,
        idempotency_key=idempotency_key,
    )
    record_audit_for_system(
        session,
        tenant_id=tenant_id,
        actor_id=f"apikey:{principal.key_id}",
        action="external.withdraw",
        entity_type="user",
        entity_id=str(user_id),
        after_state={
            "amount": str(final_amount),
            "currency": currency,
            "transaction_id": str(txn.id),
            "withdraw_all": request.withdraw_all,
            "reason": request.reason,
        },
    )
    await session.commit()
    balance, _ = await derive_balance(session, wallet.id)
    return WithdrawFromUserResponse(
        transaction_id=txn.id,
        user_id=user_id,
        amount=final_amount,
        currency=currency,
        new_balance=balance,
    )
