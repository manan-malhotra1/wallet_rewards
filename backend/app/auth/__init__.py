"""Authentication infrastructure.

Phase F.1 — Keycloak JWT validation for admin endpoints. See
`docs/security/threat-models/phase-f1-keycloak-admin-auth.md`.

The shared `KeycloakClient` singleton lives here so the JWKS cache is
process-wide. `verify_jwt` is the validation entry point. `AdminPrincipal`
is the typed result handed to route handlers.
"""
from app.auth.keycloak import KeycloakClient, keycloak_client
from app.auth.principals import AdminPrincipal
from app.auth.tokens import verify_jwt

__all__ = [
    "AdminPrincipal",
    "KeycloakClient",
    "keycloak_client",
    "verify_jwt",
]
