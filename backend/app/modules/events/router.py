"""Events module FastAPI router (Phase F.5 — admin-gated; HMAC-aware).

Two endpoints:
  - POST /api/v1/events/sources    — register an external event source (admin)
  - POST /api/v1/events/external   — synchronously ingest one event (admin)
                                     (same code path as the Kafka consumer)

Phase F.4 gated both behind `platform-admin`. Phase F.5 wires the HMAC
verifier into the ingestion path: when the source has a `shared_secret`
configured, callers must also send `X-Sasai-Signature` over the raw body.
The admin HTTP endpoint exists for test + operator use; production traffic
arrives via the Kafka consumer (`scripts/run_consumer.py`) which uses the
same `process_external_event` entrypoint and the same HMAC enforcement.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.events.schemas import (
    IngestResponse,
    SourceOut,
    SourceRegistrationRequest,
)
from app.modules.events.service import process_external_event, register_source

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


@router.post("/sources", response_model=SourceOut, status_code=201)
async def post_source(
    request: SourceRegistrationRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> SourceOut:
    """Register an external event source (Pay-PRD-0495).

    Admin-only — registering a source effectively lets that source mint
    points via reward rules. Audit row recorded.
    """
    source = await register_source(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return SourceOut.model_validate(source)


@router.post("/external", response_model=IngestResponse)
async def post_external_event(
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
    signature: str | None = Header(default=None, alias="X-Sasai-Signature", max_length=2048),
) -> IngestResponse:
    """Ingest one external event synchronously (admin-only HTTP path).

    Same business logic as the Kafka consumer. When the registered source
    has a `shared_secret`, the caller MUST also send `X-Sasai-Signature`
    over the raw body — otherwise the event is rejected with
    `integrity_check_missing`.
    """
    from app.modules.events.schemas import RawExternalEvent

    # Read RAW bytes first so the HMAC verifier sees what the client sent.
    raw_body = await fastapi_request.body()
    # Then parse to the Pydantic model for tenant + source lookups.
    import json

    payload = json.loads(raw_body or b"{}")
    raw_event = RawExternalEvent.model_validate(payload)

    _ = admin  # F.5 admin id is captured in source-register audit, not per-event
    return await process_external_event(
        session,
        raw_event,
        raw_body=raw_body,
        signature_header=signature,
    )
