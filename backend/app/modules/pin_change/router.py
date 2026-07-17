"""Change-PIN FastAPI router.

Endpoint:
  - POST /api/v1/pin/change   the authenticated user changes their own PIN.

The acting user + tenant come from the session token (never the body). The
`Idempotency-Key` header is mandatory (Pay-PRD-0200) — replays return the
original result. There is NO role gate: changing one's own PIN is universal
self-service, gated only by the current-PIN check inside the service.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user
from app.modules.pin_change.schemas import ChangePinRequest, ChangePinResponse
from app.modules.pin_change.service import change_pin

router = APIRouter(prefix="/api/v1/pin", tags=["pin"])


@router.post(
    "/change",
    response_model=ChangePinResponse,
    status_code=200,
    responses={
        200: {"description": "PIN changed; fee/tax (if any) charged."},
        401: {"description": "Missing/invalid session, wrong current PIN, or no PIN set."},
        409: {"description": "Insufficient funds for the fee."},
        422: {"description": "Validation error, new PIN == current, or service not configured."},
        423: {"description": "Account locked after too many failed current-PIN attempts."},
    },
)
async def post_change_pin(
    request: ChangePinRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> ChangePinResponse:
    """Change the authenticated user's PIN (charged self-service)."""
    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "missing_idempotency_key",
                "message": "Idempotency-Key header is required.",
            },
        )

    pin_change = await change_pin(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        request=request,
        idempotency_key=idempotency_key,
        principal=user,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return ChangePinResponse(
        status=pin_change.status,
        # The ORM types these NUMERIC columns as float; coerce back to Decimal.
        fee=Decimal(str(pin_change.fee_amount)),
        tax=Decimal(str(pin_change.tax_amount)),
        currency=pin_change.currency,
        transaction_id=pin_change.transaction_id,
    )
