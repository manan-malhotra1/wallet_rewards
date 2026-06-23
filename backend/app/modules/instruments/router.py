"""Instruments catalog FastAPI router (Phase 3 — admin-gated).

Endpoints:
  GET    /api/v1/instruments?tenant_id=&status=
  POST   /api/v1/instruments
  PATCH  /api/v1/instruments/{id}?tenant_id=
  DELETE /api/v1/instruments/{id}?tenant_id=  (soft-delete)

The catalog is the dropdown source for currency fields on Limits and
Pricing forms. Creating a new instrument with `assign_to_existing_users`
also backfills user accounts so the instrument is spendable immediately.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.instruments.schemas import (
    InstrumentCreateRequest,
    InstrumentOut,
    InstrumentUpdateRequest,
)
from app.modules.instruments.service import (
    create_instrument,
    list_instruments,
    soft_delete_instrument,
    update_instrument,
)

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
async def get_instruments(
    tenant_id: uuid.UUID,
    status: Literal["active", "disabled"] | None = None,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[InstrumentOut]:
    """List instruments for the tenant."""
    _ = admin
    instruments = await list_instruments(session, tenant_id, status=status)
    return [InstrumentOut.model_validate(i) for i in instruments]


@router.post("", response_model=InstrumentOut, status_code=201)
async def post_instrument(
    payload: InstrumentCreateRequest,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> InstrumentOut:
    """Create a new instrument; optionally backfill accounts for existing users."""
    _ = admin
    instrument = await create_instrument(session, payload)
    return InstrumentOut.model_validate(instrument)


@router.patch("/{instrument_id}", response_model=InstrumentOut)
async def patch_instrument(
    instrument_id: uuid.UUID,
    tenant_id: uuid.UUID,
    payload: InstrumentUpdateRequest,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> InstrumentOut:
    """Update symbol / display_name / description / status."""
    _ = admin
    instrument = await update_instrument(
        session, tenant_id, instrument_id, payload
    )
    return InstrumentOut.model_validate(instrument)


@router.delete("/{instrument_id}", response_model=InstrumentOut)
async def delete_instrument(
    instrument_id: uuid.UUID,
    tenant_id: uuid.UUID,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> InstrumentOut:
    """Soft-delete the instrument so it disappears from dropdowns."""
    _ = admin
    instrument = await soft_delete_instrument(
        session, tenant_id, instrument_id
    )
    return InstrumentOut.model_validate(instrument)
