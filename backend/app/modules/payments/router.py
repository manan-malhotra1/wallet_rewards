"""Payments FastAPI router.

Phase F.4 gates the P2P endpoint behind the user session token. The sender
and tenant are resolved from the session — never from the request body.
Top-up remains internal-only (called from the seed); the HTTP top-up
endpoint (Pay-PRD-0320) lands later.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user
from app.modules.payments.schemas import P2PRequest, P2PResponse
from app.modules.payments.service import p2p_transfer

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post("/p2p", response_model=P2PResponse, status_code=201)
async def post_p2p(
    request: P2PRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> P2PResponse:
    """Send funds from one user to another (Pay-PRD-0250).

    The sender is the authenticated session holder. The recipient is identified
    by phone/email/account/card. The `Idempotency-Key` header is required
    (Pay-PRD-0200) — replays with the same key return the original transaction
    without writing new ledger entries.

    Returns 201 with the transaction details on success.

    Raises:
        InvalidAuthorizationHeader (401): missing/malformed Authorization header.
        InvalidSession (401): session token unknown or expired.
        HTTPException (422): missing or blank Idempotency-Key.
    """
    # FastAPI returns 422 if the header is missing entirely; the min_length=1
    # guard rejects an empty header value.
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "missing_idempotency_key",
                "message": "Idempotency-Key header is required.",
            },
        )

    txn, recipient_user_id = await p2p_transfer(
        session,
        tenant_id=user.tenant_id,
        sender_user_id=user.id,
        recipient_identifier_type=request.recipient.identifier_type,
        recipient_identifier_value=request.recipient.identifier_value,
        amount=request.amount,
        currency=request.currency,
        idempotency_key=idempotency_key,
        sender_principal=user,
        pin=request.pin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )

    return P2PResponse(
        transaction_id=txn.id,
        status=txn.status,
        amount=txn.amount,
        currency=txn.currency,
        sender_user_id=user.id,
        recipient_user_id=recipient_user_id,
        created_at=txn.created_at,
    )
