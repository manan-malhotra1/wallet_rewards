"""Admin management of external-API keys (Epic 14 S2).

Mint a key (returning the plaintext secret exactly once), list a tenant's keys
(never exposing secrets), and revoke. All actions are audit-logged; the secret
is never written to the audit log (NFR-0170). Callers commit.
"""

from __future__ import annotations

import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.auth.secret_box import encrypt_secret
from app.modules.api_keys.schemas import ApiKeyCreateRequest
from app.modules.audit.service import record_audit_for_admin
from app.modules.user_types.service import get_user_type
from app.shared.exceptions import ApiKeyNotFound, MerchantUserRequired, TenantNotFound
from app.shared.models import (
    API_KEY_STATUS_REVOKED,
    ApiKey,
    Tenant,
    User,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is not present."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _assert_merchant_user(
    session: AsyncSession, tenant_id: UUID, merchant_user_id: UUID
) -> None:
    """Validate that merchant_user_id is a merchant-type user in this tenant.

    A merchant-bound key authorises merchant-cashin, so the referenced user must
    exist in the same tenant AND carry a type flagged `requires_merchant_profile`
    — the type row's own flag, not a hardcoded tuple, so a tenant's custom
    Business type qualifies exactly like the seeded `merchant` does. A type that
    no longer resolves fails closed here. Unknown-user and wrong-type both
    collapse to one 422 so key creation never leaks user existence across the
    admin boundary.

    Args:
        session: Async DB session (read-only).
        tenant_id: The tenant minting the key; the user must belong to it.
        merchant_user_id: The user the key will transact as.

    Raises:
        MerchantUserRequired: the id is unknown in this tenant, or the user's
            type is not backed by a merchant profile.
    """
    result = await session.execute(
        select(User).where(User.id == merchant_user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise MerchantUserRequired()
    user_type = await get_user_type(session, tenant_id, user.user_type)
    if user_type is None or not user_type.requires_merchant_profile:
        raise MerchantUserRequired()


def _generate_credentials() -> tuple[str, str]:
    """Return (public key_id, plaintext secret). key_id is a `sak_`-prefixed
    handle; the secret is high-entropy and shown to the operator only once."""
    return f"sak_{secrets.token_urlsafe(18)}", secrets.token_urlsafe(32)


async def create_api_key(
    session: AsyncSession,
    request: ApiKeyCreateRequest,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> tuple[ApiKey, str]:
    """Create a key for a tenant.

    Returns:
        (row, plaintext_secret). The secret is NOT stored in the clear — only
        its Fernet ciphertext is persisted — and is returned here once so the
        endpoint can show it to the operator.

    Raises:
        TenantNotFound: request.tenant_id is unknown.
        MerchantUserRequired: merchant_user_id is set but not a merchant-type
            user in this tenant.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    # Validate the merchant binding BEFORE minting — fail before any write.
    if request.merchant_user_id is not None:
        await _assert_merchant_user(session, request.tenant_id, request.merchant_user_id)
    key_id, secret = _generate_credentials()
    api_key = ApiKey(
        tenant_id=request.tenant_id,
        key_id=key_id,
        secret_encrypted=encrypt_secret(secret),
        label=request.label,
        merchant_user_id=request.merchant_user_id,
    )
    session.add(api_key)
    await session.flush()
    record_audit_for_admin(
        session,
        admin,
        tenant_id=request.tenant_id,
        action="api_key.created",
        entity_type="api_key",
        entity_id=str(api_key.id),
        after_state={  # never the secret; merchant_user_id is not sensitive
            "key_id": key_id,
            "label": request.label,
            "merchant_user_id": (
                str(request.merchant_user_id) if request.merchant_user_id else None
            ),
        },
        ip_address=ip_address,
    )
    return api_key, secret


async def list_api_keys(session: AsyncSession, tenant_id: UUID) -> list[ApiKey]:
    """Return a tenant's keys, newest first. Secrets are never included."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    session: AsyncSession,
    key_pk: UUID,
    tenant_id: UUID,
    *,
    admin: AdminPrincipal,
    ip_address: str | None = None,
) -> ApiKey:
    """Revoke a key. Tenant-isolated — a key in another tenant returns 404.

    Raises:
        ApiKeyNotFound: no key with that id in this tenant.
    """
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_pk, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise ApiKeyNotFound()
    before = api_key.status
    api_key.status = API_KEY_STATUS_REVOKED
    record_audit_for_admin(
        session,
        admin,
        tenant_id=tenant_id,
        action="api_key.revoked",
        entity_type="api_key",
        entity_id=str(key_pk),
        before_state={"status": before},
        after_state={"status": API_KEY_STATUS_REVOKED},
        ip_address=ip_address,
    )
    return api_key
