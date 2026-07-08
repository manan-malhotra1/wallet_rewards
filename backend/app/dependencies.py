"""Shared FastAPI dependencies.

Phase F.1 added Keycloak admin auth (`get_current_admin`, `require_admin_role`).
PIN/OTP user auth (`get_current_user`) lands in Phase F.2.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Header

from app.auth import AdminPrincipal, UserPrincipal, verify_jwt
from app.auth.sessions import read_session
from app.auth.tokens import extract_bearer_token
from app.database import get_async_session
from app.shared.exceptions import (
    InsufficientRole,
    InvalidAuthorizationHeader,
    InvalidSession,
)

__all__ = [
    "get_async_session",
    "get_current_admin",
    "get_current_user",
    "require_admin_role",
]


async def get_current_admin(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AdminPrincipal:
    """Verify the Keycloak JWT on the request and return the typed admin.

    Order of checks:
      1. Authorization header present + `Bearer <token>` format.
      2. JWT header readable, alg=RS256, kid known.
      3. Signature verifies against Keycloak's JWKS.
      4. `exp` in the future; `iss` matches our realm.

    Returns:
        AdminPrincipal with `id`, `username`, and frozen role set.

    Raises:
        InvalidAuthorizationHeader (401): missing/malformed header.
        InvalidToken (401): bad signature, header, or claims.
        InvalidAlgorithm (401): alg not in RS256 whitelist.
        TokenExpired (401): exp in past.
        UnknownSigningKey (401): kid not in JWKS.
    """
    token = extract_bearer_token(authorization)
    claims = await verify_jwt(token)

    roles = frozenset(claims.get("realm_access", {}).get("roles", []))
    return AdminPrincipal(
        id=str(claims.get("sub", "")),
        username=str(claims.get("preferred_username", "")),
        roles=roles,
    )


def require_admin_role(
    role: str,
) -> Callable[[AdminPrincipal], Coroutine[Any, Any, AdminPrincipal]]:
    """Build a FastAPI dependency that enforces a realm role on top of admin auth.

    Use:
        @router.post(
            "/sweep",
            dependencies=[Depends(require_admin_role("platform-admin"))],
        )

    Or accept the principal in the handler:
        async def post_sweep(
            admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
            ...
        ): ...

    Args:
        role: The Keycloak realm role required (e.g. "platform-admin",
            "finance-reviewer", "support-agent").

    Returns:
        An async dependency that returns the AdminPrincipal if the role is
        held, or raises InsufficientRole (403).
    """

    async def _checker(
        admin: AdminPrincipal = Depends(get_current_admin),
    ) -> AdminPrincipal:
        if not admin.has_role(role):
            raise InsufficientRole(role)
        return admin

    return _checker


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserPrincipal:
    """Validate the session_token on the request and return the typed user.

    This is the user-side equivalent of `get_current_admin`. It looks up the
    session in Redis (sliding TTL — every authenticated request extends the
    session). Sessions are issued by `/auth/pin` and invalidated by
    `/auth/logout`. Identifiers are coerced from the JSON string payload to
    typed UUIDs before construction — services compare these against
    SQLAlchemy-returned UUIDs.

    Raises:
        InvalidAuthorizationHeader: 401 — missing/malformed header.
        InvalidSession: 401 — token unknown or expired.
    """
    from uuid import UUID

    # Extract Bearer token using the same helper as admin auth (it raises
    # InvalidAuthorizationHeader on malformed input).
    token = extract_bearer_token(authorization)

    payload = await read_session(token, refresh_ttl=True)
    if payload is None:
        raise InvalidSession()

    return UserPrincipal(
        id=UUID(payload["user_id"]),
        tenant_id=UUID(payload["tenant_id"]),
        channel=payload["channel"],
    )


# Silence unused-import linting on extract_bearer_token (it's used above).
_ = (InvalidAuthorizationHeader,)
