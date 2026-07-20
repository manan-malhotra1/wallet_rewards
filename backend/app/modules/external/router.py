"""External partner API router (Epic 14 S4).

`POST /api/v1/external/users` — HMAC-authenticated (see auth.api_key), tenant
derived from the API key, reusing identity.create_user. Idempotent on the
required `Idempotency-Key` (Pay-PRD-0200): a retry with a key already used for a
successful create replays the original user (200); a NEW key whose identifier
is already taken is a genuine 409. Business logic lives in the service.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import ApiKeyPrincipal, require_api_key
from app.database import get_async_session
from app.modules.external.schemas import (
    ExternalCreateUserRequest,
    ExternalFundRequest,
    ExternalWithdrawRequest,
    MerchantCashinRequest,
    MerchantCashinResponse,
)
from app.modules.external.service import (
    external_create_user,
    external_fund,
    external_withdraw,
    merchant_cashin,
)
from app.modules.identity.schemas import UserOut
from app.modules.treasury.schemas import FundUserResponse, WithdrawFromUserResponse

router = APIRouter(prefix="/api/v1/external", tags=["external"])


@router.post(
    "/users",
    response_model=UserOut,
    status_code=201,
    summary="Create a user",
    responses={
        200: {"description": "Idempotent replay — same Idempotency-Key as a prior create."},
        401: {"description": "Missing or invalid API key / signature."},
        409: {"description": "The identifier is already registered to another user."},
        422: {
            "description": "Validation error — e.g. no email/phone identifier, "
            "or a missing Idempotency-Key header."
        },
        429: {"description": "Per-key rate limit exceeded."},
    },
)
async def create_external_user(
    payload: ExternalCreateUserRequest,
    response: Response,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> UserOut:
    """Create a user in the API key's tenant, reusing the identity service.

    The tenant comes from `principal` (the key), never the body. Idempotency is
    keyed on the `Idempotency-Key` header: a retry with a key already used for a
    successful create replays that user (200); a NEW key colliding with an
    existing identifier is a genuine 409. The service does all the work.
    """
    user, created = await external_create_user(
        session, principal=principal, payload=payload, idempotency_key=idempotency_key
    )
    # A replay (not a fresh create) signals 200 instead of the default 201,
    # mirroring how the money endpoints surface an idempotent replay.
    if not created:
        response.status_code = 200
    return UserOut.model_validate(user)


_MONEY_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing or invalid API key / signature."},
    404: {"description": "The identifier does not resolve to a user/wallet in the key's tenant."},
    409: {"description": "Insufficient funds, or nothing to withdraw (empty wallet)."},
    422: {"description": "Validation error, or a configured limit was exceeded."},
    429: {"description": "Per-key rate limit exceeded."},
}


@router.post(
    "/fund",
    response_model=FundUserResponse,
    status_code=201,
    summary="Fund a user's wallet",
    responses=_MONEY_RESPONSES,
)
async def fund_external(
    payload: ExternalFundRequest,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> FundUserResponse:
    """Credit a user's wallet in the API key's tenant.

    Tenant comes from the key, never the body. The `Idempotency-Key` header is
    required and is used as the ledger key — a retry returns the original result
    without double-crediting.
    """
    return await external_fund(
        session, principal=principal, request=payload, idempotency_key=idempotency_key
    )


@router.post(
    "/withdraw",
    response_model=WithdrawFromUserResponse,
    status_code=201,
    summary="Withdraw from a user's wallet",
    responses=_MONEY_RESPONSES,
)
async def withdraw_external(
    payload: ExternalWithdrawRequest,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> WithdrawFromUserResponse:
    """Debit a user's wallet in the API key's tenant.

    Send `amount`, or `withdraw_all: true` (no amount) to pull the full
    available balance. Tenant from the key; idempotent on the required
    `Idempotency-Key`.
    """
    return await external_withdraw(
        session, principal=principal, request=payload, idempotency_key=idempotency_key
    )


_MERCHANT_CASHIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing or invalid API key / signature."},
    403: {"description": "The API key is not bound to a merchant."},
    404: {"description": "The consumer identifier or a wallet doesn't resolve in the tenant."},
    409: {"description": "The merchant's wallet has insufficient funds."},
    422: {"description": "Validation error, a limit exceeded, or the service isn't configured."},
    429: {"description": "Per-key rate limit exceeded."},
}


@router.post(
    "/merchant-cashin",
    response_model=MerchantCashinResponse,
    status_code=201,
    summary="Merchant funds a consumer from its own wallet",
    responses=_MERCHANT_CASHIN_RESPONSES,
)
async def merchant_cashin_external(
    payload: MerchantCashinRequest,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> MerchantCashinResponse:
    """Fund a consumer from the merchant's own wallet (merchant-bound key).

    The merchant is the key's `merchant_user_id` (never the body); the consumer
    is resolved by identifier. Fee/commission/tax are borne by the merchant. The
    required `Idempotency-Key` is the ledger key — a retry returns the original
    result without double-moving money.
    """
    return await merchant_cashin(
        session, principal=principal, request=payload, idempotency_key=idempotency_key
    )
