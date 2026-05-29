"""Events module FastAPI router (Phase C test-only endpoints).

Two endpoints:
  - POST /api/v1/events/sources    — register an external event source
  - POST /api/v1/events/external   — synchronously ingest one event
                                     (same code path as the Kafka consumer)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.modules.events.schemas import (
    IngestResponse,
    RawExternalEvent,
    SourceOut,
    SourceRegistrationRequest,
)
from app.modules.events.service import process_external_event, register_source

router = APIRouter(prefix="/api/v1/events", tags=["events (test-only)"])


@router.post("/sources", response_model=SourceOut, status_code=201)
async def post_source(
    request: SourceRegistrationRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SourceOut:
    """Register an external event source (Pay-PRD-0495)."""
    source = await register_source(session, request)
    return SourceOut.model_validate(source)


@router.post("/external", response_model=IngestResponse)
async def post_external_event(
    event: RawExternalEvent,
    session: AsyncSession = Depends(get_async_session),
) -> IngestResponse:
    """Ingest one external event synchronously.

    Same business logic as the Kafka consumer (`scripts/run_consumer.py`).
    Returns the outcome and any rule firings.
    """
    return await process_external_event(session, event)
