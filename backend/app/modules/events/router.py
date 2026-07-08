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

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.config import settings
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.events.schemas import (
    IngestResponse,
    SourceOut,
    SourceRegistrationRequest,
)
from app.modules.events.service import process_external_event, register_source
from app.shared.exceptions import AppHTTPException

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


# --- Dev-only simulator routes ---------------------------------------------
# Both routes below are gated by `settings.SIMULATOR_DEV_MODE`. They return
# 404 when the flag is unset so they don't even show up in production specs.


@router.post("/sim-ingest", response_model=IngestResponse)
async def post_sim_ingest_event(
    fastapi_request: Request,
    session: AsyncSession = Depends(get_async_session),
    signature: str | None = Header(default=None, alias="X-Sasai-Signature", max_length=2048),
) -> IngestResponse:
    """Mobile-simulator's synchronous HTTP ingest path.

    Same business logic as `POST /external` but admin auth is replaced
    by the source's HMAC signature alone. Caller proves legitimacy by
    knowing the source's `shared_secret` — the same trust model real
    external event sources use in production.

    Requirements:
      - `settings.SIMULATOR_DEV_MODE` must be True (else 404)
      - The referenced `source_key` MUST have `shared_secret` configured
        (process_external_event will reject with `integrity_check_missing`
        otherwise)
      - `X-Sasai-Signature` header MUST validate against the body
    """
    if not settings.SIMULATOR_DEV_MODE:
        raise HTTPException(status_code=404)

    import json

    from app.modules.events.schemas import RawExternalEvent

    raw_body = await fastapi_request.body()
    payload = json.loads(raw_body or b"{}")
    raw_event = RawExternalEvent.model_validate(payload)

    return await process_external_event(
        session,
        raw_event,
        raw_body=raw_body,
        signature_header=signature,
    )


@router.get("/sim-bootstrap")
async def get_sim_bootstrap(
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Return tenant + seeded-user ids the simulator needs at startup.

    Looks up the first tenant in the DB and returns it along with the
    user ids of any phone identifiers that match the simulator's
    expected seed phones. Saves the operator from copying UUIDs.

    Gated by SIMULATOR_DEV_MODE. Returns:
        {
          "tenant_id": "<uuid>",
          "tenant_name": "Sasai-ZA",
          "users": {"+27825550001": "<uuid>", "+27825550002": "<uuid>"}
        }
    """
    if not settings.SIMULATOR_DEV_MODE:
        raise HTTPException(status_code=404)

    from sqlalchemy import select

    from app.shared.models import Tenant, UserIdentifier

    tenant_row = (
        (await session.execute(select(Tenant).order_by(Tenant.created_at.asc()))).scalars().first()
    )
    if tenant_row is None:
        raise AppHTTPException(404, "no_tenant_seeded", "No tenant exists yet — run `make seed`.")

    phones = (
        (
            await session.execute(
                select(UserIdentifier).where(
                    UserIdentifier.tenant_id == tenant_row.id,
                    UserIdentifier.identifier_type == "phone",
                )
            )
        )
        .scalars()
        .all()
    )
    user_by_phone = {ident.identifier_value: str(ident.user_id) for ident in phones}

    return {
        "tenant_id": str(tenant_row.id),
        "tenant_name": tenant_row.name,
        "users": user_by_phone,
    }


@router.post("/sim-kafka-produce", status_code=202)
async def post_sim_kafka_produce(
    fastapi_request: Request,
) -> dict[str, Any]:
    """Mobile-simulator's Kafka producer path.

    Produces one message to `wallet.events.external`. The existing
    Kafka consumer (`scripts/run_consumer.py`) picks it up and runs the
    same `process_external_event` pipeline asynchronously.

    Returns `{queued: True, topic, partition_key}` on the producer
    confirmation. The simulator polls /me/wallet to see when the reward
    lands.

    Gated identically to `/sim-ingest`. Confluent-kafka is already a
    backend dependency, so no new deps are introduced.
    """
    if not settings.SIMULATOR_DEV_MODE:
        raise HTTPException(status_code=404)

    import json

    from confluent_kafka import Producer

    from app.config import Topics

    raw_body = await fastapi_request.body()
    payload = json.loads(raw_body or b"{}")
    user_id = payload.get("user_id")
    if not user_id:
        raise AppHTTPException(
            422,
            "missing_user_id",
            "Event body must include user_id (Kafka partition key).",
        )

    producer = Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
    producer.produce(
        topic=Topics.EVENTS_EXTERNAL,
        key=str(user_id).encode("utf-8"),
        value=raw_body,
    )
    producer.flush(timeout=5)
    return {
        "queued": True,
        "topic": Topics.EVENTS_EXTERNAL,
        "partition_key": str(user_id),
    }
