"""Airtime recharge FastAPI router (Epic 17).

Endpoints:
  - POST /api/v1/airtime/recharge   user-initiated purchase (auth-gated)
  - GET  /api/v1/airtime/{id}       tenant-scoped status lookup (poll)

Response codes encode the sync/async split (see the airtime design plan):
  - 200 when the provider resolved synchronously (COMPLETED or REVERSED),
  - 202 when the recharge is still PENDING (client polls / awaits the callback).
The connection is never held for the async callback — the provider "sync
attempt" is bounded, so a slow provider returns 202 immediately.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal, UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user, require_admin_role
from app.modules.airtime.schemas import (
    AirtimeRechargeOut,
    AirtimeRechargeRequest,
    AirtimeResolveRequest,
)
from app.modules.airtime.service import (
    get_recharge,
    process_provider_callback,
    purchase_airtime,
    resolve_recharge,
)
from app.shared.models import AIRTIME_STATUS_PENDING

router = APIRouter(prefix="/api/v1/airtime", tags=["airtime"])


@router.post(
    "/recharge",
    response_model=AirtimeRechargeOut,
    status_code=200,
    responses={
        200: {"description": "Provider resolved synchronously (COMPLETED or REVERSED)."},
        202: {"description": "Accepted; still PENDING — poll GET /{id} or await the callback."},
        401: {"description": "Missing or invalid session token."},
        403: {"description": "The user's role does not permit airtime."},
        409: {"description": "Insufficient funds."},
        422: {"description": "Validation error, or no airtime merchant configured."},
    },
)
async def post_recharge(
    request: AirtimeRechargeRequest,
    fastapi_request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> AirtimeRechargeOut:
    """Buy airtime: reserve funds, then attempt provider provisioning.

    The buyer + tenant come from the session token (never the body). The
    `Idempotency-Key` header is required (Pay-PRD-0200) — replays return the
    original recharge. Returns 200 for a synchronously-resolved recharge, 202
    when it is still PENDING.
    """
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "missing_idempotency_key",
                "message": "Idempotency-Key header is required.",
            },
        )

    recharge, earned_points = await purchase_airtime(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user=user,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
        request=request,
        idempotency_key=idempotency_key,
    )
    if recharge.status == AIRTIME_STATUS_PENDING:
        response.status_code = status.HTTP_202_ACCEPTED
    # earned_points isn't an ORM attribute — set it after validating the resource.
    out = AirtimeRechargeOut.model_validate(recharge)
    out.earned_points = earned_points
    return out


@router.get("/{recharge_id}", response_model=AirtimeRechargeOut)
async def get_recharge_route(
    recharge_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> AirtimeRechargeOut:
    """Auth-gated recharge lookup — tenant-scoped by the session token."""
    recharge = await get_recharge(session, recharge_id, user.tenant_id, user.id)
    return AirtimeRechargeOut.model_validate(recharge)


@router.post("/{recharge_id}/callback", response_model=AirtimeRechargeOut)
async def post_callback(
    recharge_id: UUID,
    fastapi_request: Request,
    signature: str = Header(..., alias="X-Sasai-Signature", min_length=1, max_length=2048),
    session: AsyncSession = Depends(get_async_session),
) -> AirtimeRechargeOut:
    """HMAC-verified provider callback — finalises a PENDING recharge.

    The provider POSTs an `AirtimeCallbackRequest` body signed with the
    merchant's callback secret. Verification is against the RAW body, read here
    before Pydantic parsing. No Authorization header — the HMAC is the auth.
    """
    raw_body = await fastapi_request.body()
    recharge = await process_provider_callback(
        session,
        recharge_id=recharge_id,
        raw_body=raw_body,
        signature_header=signature,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return AirtimeRechargeOut.model_validate(recharge)


@router.post("/{recharge_id}/resolve", response_model=AirtimeRechargeOut)
async def post_resolve(
    recharge_id: UUID,
    request: AirtimeResolveRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> AirtimeRechargeOut:
    """Admin operator override — resolve a stuck PENDING recharge (reconciliation).

    For when the provider never called back: COMPLETED settles the reservation,
    REVERSED refunds the user. Platform-admin only; audited.
    """
    recharge = await resolve_recharge(
        session,
        recharge_id,
        request,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return AirtimeRechargeOut.model_validate(recharge)
