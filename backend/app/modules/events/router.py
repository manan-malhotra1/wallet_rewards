"""Events module FastAPI router (Phase F.4 — admin-gated).

Two endpoints:
  - POST /api/v1/events/sources    — register an external event source (admin)
  - POST /api/v1/events/external   — synchronously ingest one event (admin)
                                     (same code path as the Kafka consumer)

Phase F.4 gates both behind `platform-admin`. Phase F.5 will replace the
HTTP `/external` endpoint with HMAC-verified consumption from Kafka — the
HTTP path is admin-only because event ingestion mints reward points.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.events.schemas import (
    IngestResponse,
    RawExternalEvent,
    SourceOut,
    SourceRegistrationRequest,
)
from app.modules.events.service import process_external_event, register_source

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("/sources", response_model=SourceOut, status_code=201)
async def post_source(
    request: SourceRegistrationRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SourceOut:
    """Register an external event source (Pay-PRD-0495).

    Admin-only — registering a source effectively lets that source mint
    points via reward rules.
    """
    _ = admin  # F.5 will use admin.id for audit_log writes
    source = await register_source(session, request)
    return SourceOut.model_validate(source)


@router.post("/external", response_model=IngestResponse)
async def post_external_event(
    event: RawExternalEvent,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> IngestResponse:
    """Ingest one external event synchronously.

    Admin-only HTTP path. Same business logic as the Kafka consumer
    (`scripts/run_consumer.py`). Returns the outcome and any rule firings.
    """
    _ = admin
    return await process_external_event(session, event)
