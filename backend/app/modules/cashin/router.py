"""Agent cash-in FastAPI router (Pricing v2 Epic 21).

Endpoint:
  - POST /api/v1/cashin   agent-initiated deposit into a customer's wallet.

The agent + tenant come from the session token (never the body). The
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
from app.modules.cashin.schemas import CashInRequest, CashInResponse
from app.modules.cashin.service import cash_in

router = APIRouter(prefix="/api/v1/cashin", tags=["cashin"])


@router.post(
    "",
    response_model=CashInResponse,
    status_code=201,
    responses={
        201: {"description": "Customer funded; agent commission + fee/tax settled."},
        401: {"description": "Missing or invalid session token."},
        403: {"description": "The agent's role does not permit cash_in."},
        404: {"description": "Unknown customer identifier or missing wallet."},
        409: {"description": "Insufficient funds on the agent float."},
        422: {"description": "Validation error, or self cash-in."},
    },
)
async def post_cash_in(
    request: CashInRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    agent: UserPrincipal = Depends(get_current_user),
) -> CashInResponse:
    """Fund a customer's wallet from the agent's e-float; pay the agent a commission."""
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "missing_idempotency_key",
                "message": "Idempotency-Key header is required.",
            },
        )

    txn, customer_user_id, earned_points = await cash_in(
        session,
        tenant_id=agent.tenant_id,
        agent_user_id=agent.id,
        request=request,
        idempotency_key=idempotency_key,
        agent=agent,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return CashInResponse(
        transaction_id=txn.id,
        reference=txn.reference,
        status=txn.status,
        amount=request.amount,
        # The ORM types these NUMERIC columns as float; coerce back to Decimal.
        fee=Decimal(str(txn.fee_amount)),
        commission=Decimal(str(txn.commission_amount)),
        tax=Decimal(str(txn.tax_amount)),
        currency=txn.currency,
        customer_user_id=customer_user_id,
        earned_points=earned_points,
    )
