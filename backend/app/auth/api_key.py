"""API-key + HMAC request auth for the external partner API (Epic 14 S3).

Flow (Decision D3):
  1. Resolve the ACTIVE api_keys row by its public `key_id` (X-Sasai-Api-Key).
     Unknown or revoked -> ApiKeyInvalid (no existence leak, NFR-0220).
  2. Recover the key secret (Fernet-decrypt) and verify the request's
     X-Sasai-Signature over the raw body via `auth.hmac.verify_signature`
     (300s replay window, NFR-0210).
  3. Stamp `last_used_at` and return a tenant-scoped principal. The tenant is
     taken FROM the key, never from the request body (no cross-tenant writes).

`verify_api_key_request` is the DB-backed core; `require_api_key` is the thin
FastAPI dependency that pulls the headers + raw body off the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hmac import verify_signature
from app.auth.secret_box import decrypt_secret
from app.database import get_async_session
from app.shared.exceptions import ApiKeyInvalid
from app.shared.models import API_KEY_STATUS_ACTIVE, ApiKey


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """The authenticated external caller — which tenant, via which key."""

    tenant_id: UUID
    key_id: str


async def verify_api_key_request(
    session: AsyncSession,
    *,
    key_id: str,
    signature_header: str,
    raw_body: bytes,
    now: int | None = None,
) -> ApiKeyPrincipal:
    """Authenticate an external request from its API key + HMAC signature.

    Args:
        session: Async DB session. NOT committed here — the caller commits, so
            the `last_used_at` bump joins the endpoint's transaction.
        key_id: Public handle from X-Sasai-Api-Key.
        signature_header: Raw X-Sasai-Signature value.
        raw_body: Exact request body bytes the signature was computed over.
        now: Unix-seconds override for the replay-window check (tests).

    Returns:
        The tenant-scoped principal for the resolved key.

    Raises:
        ApiKeyInvalid: key_id unknown or not active.
        SignatureMalformed / SignatureTimestampSkew / InvalidSignature: raised
            by `verify_signature` when the signature is bad, stale, or absent.

    Side effects:
        Sets `api_keys.last_used_at` on the resolved row (flushed on commit).
    """
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.key_id == key_id,
            ApiKey.status == API_KEY_STATUS_ACTIVE,
        )
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise ApiKeyInvalid()

    secret = decrypt_secret(api_key.secret_encrypted)
    verify_signature(header=signature_header, raw_body=raw_body, secret=secret, now=now)

    api_key.last_used_at = datetime.now(UTC)
    return ApiKeyPrincipal(tenant_id=api_key.tenant_id, key_id=api_key.key_id)


async def require_api_key(
    request: Request,
    x_sasai_api_key: str | None = Header(default=None, alias="X-Sasai-Api-Key", max_length=64),
    x_sasai_signature: str | None = Header(
        default=None, alias="X-Sasai-Signature", max_length=2048
    ),
    session: AsyncSession = Depends(get_async_session),
) -> ApiKeyPrincipal:
    """FastAPI dependency that authenticates the external caller.

    A missing API key or signature is rejected the same way an invalid one is
    (ApiKeyInvalid, 401). On success the endpoint uses `principal.tenant_id`.
    """
    if not x_sasai_api_key or not x_sasai_signature:
        raise ApiKeyInvalid()
    raw_body = await request.body()
    return await verify_api_key_request(
        session,
        key_id=x_sasai_api_key,
        signature_header=x_sasai_signature,
        raw_body=raw_body,
    )
