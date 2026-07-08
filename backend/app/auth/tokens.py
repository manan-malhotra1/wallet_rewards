"""JWT verification — the only chokepoint where a raw token becomes claims.

Caller responsibilities:
  - Extract the Bearer token from the Authorization header (we provide
    `extract_bearer_token` for this).
  - Call `verify_jwt(token)` to get the validated claims dict.
  - Build a domain principal from those claims (see `principals.py`).

What `verify_jwt` guarantees on success:
  - Signature verified against Keycloak's published JWKS.
  - Algorithm is RS256 (no `none`, no HMAC).
  - `exp` is in the future.
  - `iss` matches the configured realm.
  - The kid was found in Keycloak's JWKS at some point in the last 24h.

Anything else (`aud`, `azp`, custom claims) is up to the caller.
"""

from __future__ import annotations

from typing import Any, cast

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

from app.auth.keycloak import KeycloakClient, keycloak_client
from app.shared.exceptions import (
    InvalidAlgorithm,
    InvalidAuthorizationHeader,
    InvalidToken,
    TokenExpired,
    UnknownSigningKey,
)

# Algorithm whitelist. Keycloak issues RS256 by default. We never accept HS*
# (would let any party with the shared HMAC secret forge tokens) or `none`.
_ALLOWED_ALGORITHMS = ("RS256",)


def extract_bearer_token(authorization: str | None) -> str:
    """Pull the raw JWT out of an `Authorization: Bearer ...` header value.

    Args:
        authorization: The full header value, or None if absent.

    Returns:
        The raw JWT string.

    Raises:
        InvalidAuthorizationHeader: header missing, empty, or not Bearer-prefixed.
    """
    if not authorization:
        raise InvalidAuthorizationHeader("Authorization header is missing.")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise InvalidAuthorizationHeader("Authorization header must be 'Bearer <token>'.")
    return parts[1].strip()


async def verify_jwt(token: str, *, client: KeycloakClient | None = None) -> dict[str, Any]:
    """Verify a Keycloak-issued JWT and return its claims.

    Args:
        token: The raw JWT (no Bearer prefix).
        client: Optional KeycloakClient override; defaults to the process
            singleton. Tests inject their own.

    Returns:
        The decoded, validated claims dict.

    Raises:
        InvalidToken: malformed token, bad signature, claims mismatch.
        InvalidAlgorithm: alg=none or anything outside the whitelist.
        TokenExpired: exp in the past.
        UnknownSigningKey: kid not present in JWKS even after refetch.
    """
    client = client or keycloak_client

    # 1. Decode the header without verification to find kid + alg.
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise InvalidToken("Token header is malformed.") from exc

    alg = header.get("alg")
    if alg not in _ALLOWED_ALGORITHMS:
        # Explicitly reject 'none' — common attack vector.
        raise InvalidAlgorithm(alg or "missing")

    kid = header.get("kid")
    if not kid:
        raise InvalidToken("Token header is missing kid.")

    # 2. Look up the signing key (cached JWKS, refetch on miss).
    jwk = await client.get_public_key(kid)
    if jwk is None:
        raise UnknownSigningKey()

    # 3. Verify signature + exp + iss. We intentionally do NOT verify aud
    # in F.1 — see threat model §6. F.4 narrows this.
    try:
        claims = jwt.decode(
            token,
            key=jwk,
            algorithms=list(_ALLOWED_ALGORITHMS),
            issuer=client.issuer,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": False,  # Keycloak iat clock skew tolerated
                "verify_iss": True,
                "verify_aud": False,  # Phase F.4
            },
        )
    except ExpiredSignatureError as exc:
        raise TokenExpired() from exc
    except JWTClaimsError as exc:
        # Most commonly: issuer mismatch.
        raise InvalidToken(str(exc)) from exc
    except JWTError as exc:
        raise InvalidToken("Token signature verification failed.") from exc

    return cast("dict[str, Any]", claims)
