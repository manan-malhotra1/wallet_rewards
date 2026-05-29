"""Keycloak JWKS client with TTL caching.

The realm's JSON Web Key Set is fetched lazily and cached for 24 hours
(standard JWKS rotation cadence). A cache-floor of 60 seconds is enforced
to prevent DoS via forced refetches on unknown kids.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings

# Cache TTL (24h is the standard for JWKS).
_JWKS_TTL = timedelta(hours=24)
# Floor between refetches even on cache miss — protects against DoS via bad kids.
_JWKS_REFETCH_FLOOR = timedelta(seconds=60)


class KeycloakClient:
    """Process-singleton client for fetching Keycloak realm metadata.

    Holds a single JWKS document in memory with a 24h TTL. Concurrent callers
    share one in-flight refetch via `asyncio.Lock`.
    """

    def __init__(self, base_url: str, realm: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._realm = realm
        self._jwks: dict[str, Any] | None = None
        self._fetched_at: datetime | None = None
        self._last_refetch_attempt: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def issuer(self) -> str:
        """The realm's iss claim value (used to verify token issuer)."""
        return f"{self._base_url}/realms/{self._realm}"

    @property
    def jwks_url(self) -> str:
        """Public JWKS endpoint URL on the realm."""
        return f"{self.issuer}/protocol/openid-connect/certs"

    def _cache_fresh(self) -> bool:
        """True if the JWKS cache is populated and within TTL."""
        if self._jwks is None or self._fetched_at is None:
            return False
        return datetime.now(timezone.utc) - self._fetched_at < _JWKS_TTL

    def _can_refetch(self) -> bool:
        """Floor refetches to one per minute — DoS guard."""
        if self._last_refetch_attempt is None:
            return True
        return (
            datetime.now(timezone.utc) - self._last_refetch_attempt
            > _JWKS_REFETCH_FLOOR
        )

    async def _refetch(self) -> None:
        """Fetch the JWKS over HTTPS and overwrite the cache.

        Caller must hold `self._lock`.
        """
        self._last_refetch_attempt = datetime.now(timezone.utc)
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(self.jwks_url)
            resp.raise_for_status()
            self._jwks = resp.json()
            self._fetched_at = datetime.now(timezone.utc)

    async def get_public_key(self, kid: str) -> dict[str, Any] | None:
        """Return the JWK with the given `kid` or None.

        Strategy:
          1. Use cached JWKS if still fresh and contains `kid`.
          2. If `kid` missing, attempt one refetch (respecting the refetch floor).
          3. Return None if the kid is still unknown.

        Args:
            kid: The `kid` field from a JWT header.

        Returns:
            The matching JWK dict, or None if not found.
        """
        async with self._lock:
            if not self._cache_fresh():
                await self._refetch()

        key = self._find_key(kid)
        if key is not None:
            return key

        # Cache miss — attempt one refetch (subject to floor) in case keys rotated.
        async with self._lock:
            if self._can_refetch():
                await self._refetch()
            else:
                return None

        return self._find_key(kid)

    def _find_key(self, kid: str) -> dict[str, Any] | None:
        if self._jwks is None:
            return None
        for key in self._jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    # ------------------------------------------------------------------ test hooks

    def _seed_cache_for_tests(
        self, jwks: dict[str, Any], fetched_at: datetime | None = None
    ) -> None:
        """Test-only hook: prime the cache without making an HTTP call.

        Tests use this to inject a JWKS derived from a test keypair so JWT
        verification works against an in-process signing key.
        """
        self._jwks = jwks
        self._fetched_at = fetched_at or datetime.now(timezone.utc)


# Process-wide singleton. Settings are read once at import — KEYCLOAK_URL and
# KEYCLOAK_REALM must be present in the .env (already required by Settings).
keycloak_client = KeycloakClient(
    base_url=settings.KEYCLOAK_URL,
    realm=settings.KEYCLOAK_REALM,
)
