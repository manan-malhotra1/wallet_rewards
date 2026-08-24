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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.api_key import ApiKeyPrincipal
from app.modules.accounts.service import derive_balance
from app.modules.audit.service import record_audit_for_system
from app.modules.commissions.service import calculate_commission
from app.modules.external.schemas import (
    ExternalCreateUserRequest,
    ExternalFundRequest,
    ExternalWithdrawRequest,
    MerchantCashinRequest,
    MerchantCashinResponse,
)
from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.limits.service import check_limits, check_wallet_send_limits
from app.modules.payments.service import fund
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
from app.modules.taxes.service import calculate_tax
from app.modules.treasury.schemas import FundUserResponse, WithdrawFromUserResponse
from app.modules.treasury.service import (
    get_or_create_operator_adjustment,
    post_user_withdraw,
    resolve_user_financial_wallet,
    resolve_withdraw_amount,
)
from app.shared.exceptions import (
    AccountNotFound,
    DuplicateIdempotencyKey,
    FundingTemporarilyUnavailable,
    IdentifierAlreadyInUse,
    InsufficientFloat,
    InsufficientFunds,
    NotAMerchantKey,
    SelfTransferNotAllowed,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    ExternalUserCreation,
    Transaction,
    User,
)
from app.shared.models import ENTRY_DEBIT as _ENTRY_DEBIT

MERCHANT_CASHIN_SERVICE_CODE = "merchant_cashin"


async def _find_external_creation(
    session: AsyncSession, tenant_id: UUID, idempotency_key: str
) -> User | None:
    """Return the user recorded for this `(tenant, idempotency_key)`, or None.

    The user's identifiers are eager-loaded so a caller can serialise a
    `UserOut` without a post-commit lazy load.

    Args:
        session: Async DB session.
        tenant_id: The API key's tenant (never the body).
        idempotency_key: The partner's `Idempotency-Key` header value.

    Returns:
        The originally-created `User`, or None if the key was never recorded.
    """
    row = (
        await session.execute(
            select(ExternalUserCreation).where(
                ExternalUserCreation.tenant_id == tenant_id,
                ExternalUserCreation.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    result = await session.execute(
        select(User).options(selectinload(User.identifiers)).where(User.id == row.user_id)
    )
    return result.scalar_one()


async def external_create_user(
    session: AsyncSession,
    *,
    principal: ApiKeyPrincipal,
    payload: ExternalCreateUserRequest,
    idempotency_key: str,
) -> tuple[User, bool]:
    """Create a partner end-user, keyed idempotently on the `Idempotency-Key`.

    The idempotency KEY — not the identifier — is the replay anchor
    (Pay-PRD-0200):

    - A retry whose key was already recorded replays the original user (no new
      user, no error).
    - A NEW key whose identifier is already taken is a genuine conflict and
      propagates `IdentifierAlreadyInUse` (409) — it does NOT silently return
      the existing user (that leaked identifier existence, S4).
    - A new key with a free identifier creates the user and records the mapping.

    Privilege/trust-relevant fields are still forced server-side (S7 H1): a
    partner cannot assert identifier verification and cannot name a supervisor
    by raw id. `user_type` and `parent_identifier` ARE honoured (spec §7.3) but
    are not trusted from the body — `create_user` resolves both against THIS
    key's tenant, so an unknown or retired type is refused and a supervisor in
    another tenant is indistinguishable from a missing one.

    Args:
        session: Async DB session (committed here).
        principal: The authenticated API key — supplies the tenant + audit actor.
        payload: The restricted partner create-user payload.
        idempotency_key: The required `Idempotency-Key` header value.

    Returns:
        `(user, created)` — `created` is True for a fresh create (HTTP 201) and
        False for an idempotent replay (HTTP 200); the router maps the flag.

    Raises:
        IdentifierAlreadyInUse (409): a NEW key collided with a taken identifier.
        UnknownUserType (422): `user_type` does not resolve for the key's tenant.
        ParentNotFound (422): `parent_identifier` resolves to nobody in it.
        InvalidUserTypeParent (422): the resolved supervisor is the wrong type.

    Side effects:
        Inserts a `users` row (via identity.create_user), an
        `external_user_creations` idempotency row, and a system-actor audit row.
    """
    tenant_id = principal.tenant_id

    # Idempotency fast-path: a retry with a key we've already recorded replays
    # the original user. The KEY drives dedup, never the identifier.
    replay = await _find_external_creation(session, tenant_id, idempotency_key)
    if replay is not None:
        return replay, False

    # Force privilege/trust-relevant fields server-side (S7 H1): no
    # partner-asserted identifier verification, and no supervisor named by raw
    # id. `user_type` / `parent_identifier` pass through to `create_user`, which
    # validates both against THIS tenant — never the body.
    create_req = CreateUserRequest(
        tenant_id=tenant_id,
        identifiers=[
            IdentifierIn(
                identifier_type=i.identifier_type,
                identifier_value=i.identifier_value,
                verified=False,
            )
            for i in payload.identifiers
        ],
        profile=payload.profile,
        user_type=payload.user_type,
        parent_user_id=None,
        parent_identifier=payload.parent_identifier,
    )
    try:
        user = await create_user(session, create_req)
    except IdentifierAlreadyInUse:
        # A concurrent same-key request may have created the user between our
        # fast-path miss and this create — if the key is now recorded, replay
        # rather than 409. Otherwise it is a genuine conflict (new key, taken
        # identifier) and the 409 propagates.
        replay = await _find_external_creation(session, tenant_id, idempotency_key)
        if replay is not None:
            return replay, False
        raise

    # create_user already committed the user; record the idempotency mapping +
    # a system-actor audit row (the partner path has no admin principal, so
    # create_user did not audit) and commit them together.
    session.add(
        ExternalUserCreation(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            user_id=user.id,
        )
    )
    record_audit_for_system(
        session,
        tenant_id=tenant_id,
        actor_id=f"apikey:{principal.key_id}",
        action="user.created",
        entity_type="user",
        entity_id=str(user.id),
        after_state={
            "identifier_count": len(create_req.identifiers),
            "has_profile": create_req.profile is not None,
            "user_type": user.user_type,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent same-key request won the UNIQUE (tenant, key) race. Roll
        # back our mapping/audit and replay the winner's user (200) — a
        # concurrent retry must still replay, not 409.
        await session.rollback()
        replay = await _find_external_creation(session, tenant_id, idempotency_key)
        if replay is not None:
            return replay, False
        raise
    return user, True


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

    `request.service_code` is an optional derived service to transact under
    (spec §7, §8 — a partner key may name a derived service). Omitted -> plain
    'fund', identical to pre-existing behaviour. When supplied, resolved ONCE
    up front and used for every downstream permission / pricing / limits /
    ledger step; `base_transaction_type` on the recorded transaction is always
    'fund' regardless.

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
        # Compared against base_transaction_type (not transaction_type) so a
        # replay of a DERIVED fund service still matches — its transaction_type
        # is the derived code, but its base is always 'fund' (spec §12.1).
        if existing.base_transaction_type != "fund":
            raise DuplicateIdempotencyKey()
        balance, _ = await derive_balance(session, wallet.id)
        return FundUserResponse(
            transaction_id=existing.id,
            user_id=user_id,
            amount=Decimal(str(existing.amount)),
            currency=str(existing.currency),
            new_balance=balance,
        )

    # Resolve the service code ONCE, before any permission/pricing/limits gate,
    # so every downstream step transacts under the SAME code (spec §7, §8 — a
    # partner key may name a derived service). A partner fund has no single
    # acting wallet-user type (the partner funds an arbitrary user), so
    # user_type=None skips the WHO dimension for both resolution and the
    # channel policy check below.
    from app.modules.services.service import assert_service_allowed, resolve_service_code

    service_code = await resolve_service_code(
        session,
        tenant_id=tenant_id,
        base_code="fund",
        requested_code=request.service_code,
        user_type=None,
        channel="api",
    )

    # Per-service access policy — CHANNEL dimension only. user_type=None SKIPS
    # the WHO check and enforces only that the resolved service is allowed on
    # the "api" channel. After the idempotency fast-path, before any ledger work.
    await assert_service_allowed(
        session,
        tenant_id=tenant_id,
        transaction_type=service_code,
        user_type=None,
        channel="api",
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
        service=service_code,
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
        transaction_type=service_code,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    try:
        txn = await fund(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            amount=request.amount,
            currency=currency,
            idempotency_key=idempotency_key,
            transaction_type=service_code,
            # The BASE flow — always 'fund' regardless of which derived
            # service (if any) was resolved above (spec §12.1).
            base_transaction_type="fund",
        )
    except InsufficientFloat as exc:
        # Don't leak the operator's liquidity state / "top up from the bank"
        # remediation to a third-party partner — it's outside their control
        # (security review). Surface a generic retryable 503 instead; the
        # specific insufficient_float stays on the admin/treasury surfaces.
        raise FundingTemporarilyUnavailable() from exc
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

    `request.service_code` is an optional derived service to transact under
    (spec §7, §8 — a partner key may name a derived service). Omitted -> plain
    'withdraw', identical to pre-existing behaviour. When supplied, resolved
    ONCE up front and used for every downstream permission / pricing / limits /
    ledger step; `base_transaction_type` on the recorded transaction is always
    'withdraw' regardless.

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
        # Bind the key to the operation (S4 M-03). Compared against
        # base_transaction_type so a replay of a DERIVED withdraw service
        # still matches — see external_fund for the same reasoning.
        if existing.base_transaction_type != "withdraw":
            raise DuplicateIdempotencyKey()
        balance, _ = await derive_balance(session, wallet.id)
        return WithdrawFromUserResponse(
            transaction_id=existing.id,
            user_id=user_id,
            amount=Decimal(str(existing.amount)),
            currency=str(existing.currency),
            new_balance=balance,
        )

    # Resolve the service code ONCE, before any permission/pricing/limits gate
    # (spec §7, §8). A partner withdraw has no single acting wallet-user type,
    # so user_type=None skips the WHO dimension for both resolution and the
    # channel policy check below.
    from app.modules.services.service import assert_service_allowed, resolve_service_code

    service_code = await resolve_service_code(
        session,
        tenant_id=tenant_id,
        base_code="withdraw",
        requested_code=request.service_code,
        user_type=None,
        channel="api",
    )

    # Per-service access policy — CHANNEL dimension only (see external_fund).
    # user_type=None enforces just that the resolved service is allowed on the
    # "api" channel. After the idempotency fast-path, before any ledger work.
    await assert_service_allowed(
        session,
        tenant_id=tenant_id,
        transaction_type=service_code,
        user_type=None,
        channel="api",
    )

    # Fail-closed service gate (invariant #12). AFTER the idempotency fast-path,
    # BEFORE any ledger work: BOTH a pricing and a limit config must resolve for
    # the target user's type or the withdraw is rejected 422 here. Unconditional.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=service_code,
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
        transaction_type=service_code,
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
        transaction_type=service_code,
        # The BASE flow — always 'withdraw' regardless of which derived
        # service (if any) was resolved above (spec §12.1).
        base_transaction_type="withdraw",
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


async def _find_wallet_by_user_id(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, currency: str
) -> Account:
    """Return the user's `financial_wallet` for the currency, or 404.

    Used to resolve the funding merchant's own wallet (the merchant is named by
    the key, not by an identifier), so it looks up directly by user_id.

    Raises:
        AccountNotFound (404): no financial_wallet for this user/currency.
    """
    wallet = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one_or_none()
    if wallet is None:
        raise AccountNotFound()
    return wallet


def _net_debit(entries: list[LedgerEntryRequest], account_id: UUID) -> Decimal:
    """Net DEBIT (debits - credits) an account bears across the assembled legs.

    Used for the advisory early overdraft check on the merchant wallet; the
    AUTHORITATIVE check is the balance guard inside `post_transaction`.
    """
    total = Decimal("0")
    for entry in entries:
        if entry.account_id != account_id:
            continue
        total += entry.amount if entry.entry_type == _ENTRY_DEBIT else -entry.amount
    return total


async def merchant_cashin(
    session: AsyncSession,
    *,
    principal: ApiKeyPrincipal,
    request: MerchantCashinRequest,
    idempotency_key: str,
) -> MerchantCashinResponse:
    """Fund a consumer from a merchant's own wallet, on the merchant's API key.

    The key MUST be merchant-bound (`principal.merchant_user_id` set) — that
    merchant is the payer. The consumer recipient is resolved by identifier.
    Fee / commission / tax are assembled per the merchant's pricing config and
    the merchant bears them; the consumer receives the principal.

    The tenant always comes from the key, never the body. The partner's
    `Idempotency-Key` is the ledger transaction key, so a retry returns the
    original result without double-moving money.

    `request.service_code` is an optional derived service to transact under
    (spec §7, §8 — a partner key may name a derived service). Omitted -> plain
    'merchant_cashin', identical to pre-existing behaviour. When supplied,
    resolved ONCE up front and used for every downstream permission / pricing /
    limits / ledger step; `base_transaction_type` on the recorded transaction
    is always 'merchant_cashin' regardless.

    Raises:
        NotAMerchantKey (403): the key isn't bound to a merchant.
        UserNotFound (404): the consumer identifier doesn't resolve in the tenant.
        AccountNotFound (404): merchant or consumer has no financial_wallet.
        SelfTransferNotAllowed (422): the consumer resolves to the merchant.
        ServiceNotConfigured (422): pricing OR limit config missing for the merchant.
        InsufficientFunds (409): the merchant's wallet can't cover the outflow.
    """
    if principal.merchant_user_id is None:
        raise NotAMerchantKey()

    tenant_id = principal.tenant_id
    merchant_user_id = principal.merchant_user_id
    currency = request.currency.upper()

    # Resolve both wallets up front: the merchant (by the key's bound user id)
    # and the consumer (by identifier). resolve_user_financial_wallet can never
    # return a system wallet (user_id IS NULL is excluded), mirroring fund.
    merchant_wallet = await _find_wallet_by_user_id(
        session, tenant_id=tenant_id, user_id=merchant_user_id, currency=currency
    )
    consumer_user_id, consumer_wallet = await resolve_user_financial_wallet(
        session, tenant_id, request.identifier_type, request.identifier_value, currency
    )
    if consumer_user_id == merchant_user_id:
        raise SelfTransferNotAllowed()

    # Idempotency fast-path — return the original result before ANY limits or
    # ledger work (a replay's first move is already in the rolling caps, so
    # re-checking limits here would wrongly reject it).
    existing = await _find_by_idempotency(session, tenant_id, idempotency_key)
    if existing is not None:
        # Bind the key to the operation (S4 M-03): a key reused for a different
        # op must not silently return a mismatched txn. Compared against
        # base_transaction_type so a replay of a DERIVED merchant_cashin
        # service still matches — see external_fund for the same reasoning.
        if existing.base_transaction_type != MERCHANT_CASHIN_SERVICE_CODE:
            raise DuplicateIdempotencyKey()
        return await _build_response(
            session,
            transaction_id=existing.id,
            merchant_user_id=merchant_user_id,
            consumer_user_id=consumer_user_id,
            merchant_wallet=merchant_wallet,
            consumer_wallet=consumer_wallet,
            amount=Decimal(str(existing.amount)),
            currency=str(existing.currency),
        )

    # Resolve the service code ONCE, before any permission/pricing/limits gate
    # (spec §7, §8), on the MERCHANT's user_type (the initiator) — the key is
    # merchant-bound, so the acting wallet-user type IS known.
    from app.modules.services.service import assert_service_allowed, resolve_service_code
    from app.shared.utils.user_types import resolve_user_type

    merchant_user_type = await resolve_user_type(session, tenant_id, merchant_user_id)
    service_code = await resolve_service_code(
        session,
        tenant_id=tenant_id,
        base_code=MERCHANT_CASHIN_SERVICE_CODE,
        requested_code=request.service_code,
        user_type=merchant_user_type,
        channel="api",
    )

    # Per-service access policy, resolved on the MERCHANT's user_type (the
    # initiator) with the "api" channel. Both dimensions are enforced here.
    # After the idempotency fast-path, before any ledger work.
    await assert_service_allowed(
        session,
        tenant_id=tenant_id,
        transaction_type=service_code,
        user_type=merchant_user_type,
        channel="api",
    )

    # Fail-closed service gate (invariant #12), resolved on the MERCHANT's
    # user_type (the initiator). BOTH a pricing and a limit config must resolve
    # or the request is rejected 422 here, BEFORE any ledger work. Unconditional.
    from app.modules.pricing.service import require_pricing_and_limits

    await require_pricing_and_limits(
        session,
        tenant_id=tenant_id,
        service=service_code,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        user_id=merchant_user_id,
    )

    # Limits on the MERCHANT (the one spending), then charges.
    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=merchant_user_id,
        transaction_type=service_code,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    await check_wallet_send_limits(
        session,
        tenant_id=tenant_id,
        user_id=merchant_user_id,
        currency=currency,
        amount=request.amount,
    )

    # Pricing (slab fee + inclusive flag), commission, tax — all resolved on the
    # merchant. Missing pricing already failed closed above; a zero fee must be
    # an explicitly configured row (invariant #12), never an implicit default.
    fee_quote = await resolve_fee(
        session,
        tenant_id=tenant_id,
        user_id=merchant_user_id,
        transaction_type=service_code,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
        amount=request.amount,
    )
    commission = await calculate_commission(
        session,
        tenant_id=tenant_id,
        agent_user_id=merchant_user_id,
        transaction_type=service_code,
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
            payer_account_id=merchant_wallet.id,
            beneficiary_account_id=consumer_wallet.id,
            fee_account_id=fee_account.id,
            service_tax_account_id=service_tax_account.id,
            commission_tax_account_id=commission_tax_account.id,
            commission_pool_account_id=commission_pool.id,
            agent_account_id=merchant_wallet.id,  # any commission lands on the merchant
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

    # Advisory overdraft on the merchant float (net of any commission credit on
    # the same wallet). The AUTHORITATIVE check is the balance guard inside
    # post_transaction, which locks the merchant wallet FOR UPDATE — this is the
    # "funded merchant" requirement, so it fails closed on merchant balance (409).
    balance, reserved = await derive_balance(session, merchant_wallet.id)
    if balance - reserved < _net_debit(assembled.entries, merchant_wallet.id):
        raise InsufficientFunds()

    # Post the balanced transaction. skip_receive_cap stays False so the
    # CONSUMER's max_balance is still enforced (a genuine deposit).
    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type=service_code,
            # The BASE flow — always 'merchant_cashin' regardless of which
            # derived service (if any) was resolved above (spec §12.1).
            base_transaction_type=MERCHANT_CASHIN_SERVICE_CODE,
            currency=currency,
            entries=assembled.entries,
            initiated_by=merchant_user_id,
            amount=request.amount,
            fee_amount=assembled.fee_amount,
            commission_amount=assembled.commission_amount,
            tax_amount=assembled.tax_amount,
        ),
    )
    record_audit_for_system(
        session,
        tenant_id=tenant_id,
        actor_id=f"apikey:{principal.key_id}",
        action="external.merchant_cashin",
        entity_type="user",
        entity_id=str(consumer_user_id),
        after_state={
            "amount": str(request.amount),
            "currency": currency,
            "transaction_id": str(txn.id),
            "merchant_user_id": str(merchant_user_id),
            "fee": str(assembled.fee_amount),
            "commission": str(assembled.commission_amount),
            "tax": str(assembled.tax_amount),
            "reason": request.reason,
        },
    )
    await session.commit()
    return await _build_response(
        session,
        transaction_id=txn.id,
        merchant_user_id=merchant_user_id,
        consumer_user_id=consumer_user_id,
        merchant_wallet=merchant_wallet,
        consumer_wallet=consumer_wallet,
        amount=request.amount,
        currency=currency,
    )


async def _build_response(
    session: AsyncSession,
    *,
    transaction_id: UUID,
    merchant_user_id: UUID,
    consumer_user_id: UUID,
    merchant_wallet: Account,
    consumer_wallet: Account,
    amount: Decimal,
    currency: str,
) -> MerchantCashinResponse:
    """Assemble the response with both wallets' post-move balances."""
    merchant_balance, _ = await derive_balance(session, merchant_wallet.id)
    consumer_balance, _ = await derive_balance(session, consumer_wallet.id)
    return MerchantCashinResponse(
        transaction_id=transaction_id,
        merchant_user_id=merchant_user_id,
        consumer_user_id=consumer_user_id,
        amount=amount,
        currency=currency,
        merchant_new_balance=merchant_balance,
        consumer_new_balance=consumer_balance,
    )
