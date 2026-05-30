"""Typed principals returned by auth dependencies.

A `Principal` is "the verified, authenticated party making this request."
After `get_current_admin()` returns, route handlers can trust every field on
the principal — the JWT has been signature-checked and unexpired.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdminPrincipal:
    """The authenticated administrator behind an admin endpoint call.

    `id` is the Keycloak `sub` claim (a UUID-format string). `username` is
    `preferred_username`. `roles` is the set of realm roles claimed by the
    token (verified at signature check time).
    """

    id: str
    username: str
    roles: frozenset[str]

    def has_role(self, role: str) -> bool:
        """True if the principal holds the given realm role."""
        return role in self.roles


@dataclass(frozen=True)
class UserPrincipal:
    """The authenticated end-user behind a user-facing endpoint call.

    Built from a valid Redis-backed session_token (issued by `/auth/pin`).
    `id` and `tenant_id` are platform UUIDs; `channel` is 'mobile' or 'ussd'
    (Phase F.2 emits 'mobile' only).
    """

    id: str
    tenant_id: str
    channel: str
