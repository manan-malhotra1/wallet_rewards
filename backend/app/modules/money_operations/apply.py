"""Execute an approved money-operation request against the treasury service.

Epic 18. Once N-eyes quorum is reached, `apply_money_operation` dispatches on
`operation` to the matching treasury service function (verbatim — no new ledger
legs; each already funnels through `post_transaction` and its balance guard).

Two invariants shape this module:
  - Attribution: the MAKER who proposed is passed as the acting admin, so the
    treasury audit row is attributed to whoever authored the movement.
  - Idempotency (invariant #2): a DETERMINISTIC key `money-op-<request-id>` is
    threaded into the treasury fn / `post_transaction`, so a re-approval or
    replay of the same request can never double-post — the second post returns
    the original transaction.

`applied_transaction_id` is captured for fund/withdraw/adjust (create_bank_mirror
produces no transaction). The treasury fn commits internally (persisting the
request→APPLIED transition the caller staged beforehand, in the SAME commit); the
transaction-id linkage is then written in a small follow-up commit, since the id
only exists once that commit has run.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.money_operations.schemas import (
    AdjustSystemWalletPayload,
    CreateBankMirrorPayload,
    FundUserPayload,
    WithdrawUserPayload,
)
from app.modules.treasury.service import (
    adjust_system_wallet,
    create_bank_mirror,
    fund_user,
    withdraw_from_user,
)
from app.shared.models import (
    MONEY_OP_ADJUST_SYSTEM,
    MONEY_OP_CREATE_BANK_MIRROR,
    MONEY_OP_FUND_USER,
    MONEY_OP_WITHDRAW_USER,
    MoneyOperationRequest,
)


def _maker_principal(request: MoneyOperationRequest) -> AdminPrincipal:
    """Reconstruct the proposing maker as the acting admin for audit attribution.

    Only the `id` (Keycloak sub) is needed downstream — the treasury audit writer
    reads `admin.id`. Username/roles aren't available at apply time and aren't
    used, so they are left empty.
    """
    return AdminPrincipal(id=request.maker_admin_id, username="", roles=frozenset())


def _default_reason(request: MoneyOperationRequest) -> str:
    """A fallback audit reason when the maker supplied none."""
    return f"Money operation {request.operation} (request {request.id})"


async def apply_money_operation(
    session: AsyncSession,
    request: MoneyOperationRequest,
    *,
    ip_address: str | None = None,
) -> MoneyOperationRequest:
    """Execute an APPLIED money-operation request via its treasury function.

    Dispatches on `request.operation`, threading the maker as the acting admin
    and a deterministic idempotency key. Sets `applied_transaction_id` for the
    three ledger-moving operations (create_bank_mirror has no transaction).

    Returns:
        The same request, with `applied_transaction_id` set where applicable.

    Side effects:
        Commits via the treasury fn (money movement + staged request mutations),
        then commits once more to persist `applied_transaction_id`.
    """
    admin = _maker_principal(request)
    idempotency_key = f"money-op-{request.id}"
    reason_fallback = _default_reason(request)

    if request.operation == MONEY_OP_FUND_USER:
        fund_payload = FundUserPayload.model_validate(request.payload)
        fund_result = await fund_user(
            session,
            tenant_id=request.tenant_id,
            identifier_type=fund_payload.identifier_type,
            identifier_value=fund_payload.identifier_value,
            amount=fund_payload.amount,
            currency=fund_payload.currency,
            reason=fund_payload.reason or reason_fallback,
            admin=admin,
            ip_address=ip_address,
            idempotency_key=idempotency_key,
        )
        request.applied_transaction_id = fund_result.transaction_id
    elif request.operation == MONEY_OP_WITHDRAW_USER:
        withdraw_payload = WithdrawUserPayload.model_validate(request.payload)
        withdraw_result = await withdraw_from_user(
            session,
            tenant_id=request.tenant_id,
            identifier_type=withdraw_payload.identifier_type,
            identifier_value=withdraw_payload.identifier_value,
            amount=withdraw_payload.amount,
            withdraw_all=withdraw_payload.withdraw_all,
            currency=withdraw_payload.currency,
            bank_mirror_account_id=withdraw_payload.bank_mirror_account_id,
            wallet_type=withdraw_payload.wallet_type,
            reason=withdraw_payload.reason or reason_fallback,
            admin=admin,
            ip_address=ip_address,
            idempotency_key=idempotency_key,
        )
        request.applied_transaction_id = withdraw_result.transaction_id
    elif request.operation == MONEY_OP_ADJUST_SYSTEM:
        adjust_payload = AdjustSystemWalletPayload.model_validate(request.payload)
        adjust_result = await adjust_system_wallet(
            session,
            tenant_id=request.tenant_id,
            account_id=adjust_payload.account_id,
            amount=adjust_payload.amount,
            bank_mirror_account_id=adjust_payload.bank_mirror_account_id,
            reason=adjust_payload.reason or reason_fallback,
            admin=admin,
            ip_address=ip_address,
            idempotency_key=idempotency_key,
        )
        request.applied_transaction_id = adjust_result.transaction_id
    else:  # MONEY_OP_CREATE_BANK_MIRROR — no transaction produced.
        assert request.operation == MONEY_OP_CREATE_BANK_MIRROR
        bank_payload = CreateBankMirrorPayload.model_validate(request.payload)
        await create_bank_mirror(
            session,
            tenant_id=request.tenant_id,
            currency=bank_payload.currency,
            name=bank_payload.name,
            admin=admin,
            ip_address=ip_address,
        )
        return request

    # Persist the transaction-id linkage (the id only exists post-commit).
    await session.commit()
    return request
