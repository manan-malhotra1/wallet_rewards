"""Payments FastAPI router.

Phase B exposes only the P2P endpoint. Top-up is internal-only for now
(called from the seed); the HTTP top-up endpoint (Pay-PRD-0320) lands later.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.modules.payments.schemas import P2PRequest, P2PResponse
from app.modules.payments.service import p2p_transfer

router = APIRouter(prefix="/api/v1/payments", tags=["payments (test-only)"])


@router.post("/p2p", response_model=P2PResponse, status_code=201)
async def post_p2p(
    request: P2PRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> P2PResponse:
    """Send funds from one user to another (Pay-PRD-0250).

    Phase B endpoint is TEST-ONLY (no auth). The `Idempotency-Key` header is
    required (Pay-PRD-0200). Replays with the same key return the original
    transaction without writing new ledger entries.

    Returns 201 with the transaction details on success.
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
        tenant_id=request.tenant_id,
        sender_user_id=request.sender_user_id,
        recipient_identifier_type=request.recipient.identifier_type,
        recipient_identifier_value=request.recipient.identifier_value,
        amount=request.amount,
        currency=request.currency,
        idempotency_key=idempotency_key,
    )

    return P2PResponse(
        transaction_id=txn.id,
        status=txn.status,
        amount=txn.amount,
        currency=txn.currency,
        sender_user_id=request.sender_user_id,
        recipient_user_id=recipient_user_id,
        created_at=txn.created_at,
    )
