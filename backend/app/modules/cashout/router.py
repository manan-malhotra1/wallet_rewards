"""Subscriber cash-out FastAPI router.

Endpoint:
  - POST /api/v1/cashout   subscriber-initiated send of money to an agent.

The subscriber + tenant come from the session token (never the body). The
`Idempotency-Key` header is mandatory (Pay-PRD-0200) — replays return the
original transaction.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user
from app.modules.cashout.schemas import CashOutRequest, CashOutResponse
from app.modules.cashout.service import cash_out

router = APIRouter(prefix="/api/v1/cashout", tags=["cashout"])


@router.post(
    "",
    response_model=CashOutResponse,
    status_code=201,
    responses={
        201: {"description": "Agent credited; subscriber debited; fee/commission/tax settled."},
        401: {"description": "Missing or invalid session token."},
        403: {"description": "The subscriber's role does not permit cashout."},
        404: {"description": "Unknown agent identifier or missing wallet."},
        409: {"description": "Insufficient funds on the subscriber's wallet."},
        422: {"description": "Validation error, self cash-out, or recipient not an agent."},
    },
)
async def post_cash_out(
    request: CashOutRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    subscriber: UserPrincipal = Depends(get_current_user),
) -> CashOutResponse:
    """Send money from the subscriber's wallet to an agent; agent earns commission."""
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "missing_idempotency_key",
                "message": "Idempotency-Key header is required.",
            },
        )

    txn, agent_user_id = await cash_out(
        session,
        tenant_id=subscriber.tenant_id,
        subscriber_user_id=subscriber.id,
        request=request,
        idempotency_key=idempotency_key,
        subscriber=subscriber,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return CashOutResponse(
        transaction_id=txn.id,
        reference=txn.reference,
        status=txn.status,
        amount=request.amount,
        # The ORM types these NUMERIC columns as float; coerce back to Decimal.
        fee=Decimal(str(txn.fee_amount)),
        commission=Decimal(str(txn.commission_amount)),
        tax=Decimal(str(txn.tax_amount)),
        currency=txn.currency,
        agent_user_id=agent_user_id,
    )
