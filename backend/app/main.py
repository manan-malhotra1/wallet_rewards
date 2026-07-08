"""FastAPI entry point.

Registers all module routers and the global exception handler that converts
AppHTTPException instances into the standard error envelope.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.modules.accounts import router as accounts_router
from app.modules.api_keys import router as api_keys_router
from app.modules.budgets import router as budgets_router
from app.modules.catalog import router as catalog_router
from app.modules.events import router as events_router
from app.modules.external import router as external_router
from app.modules.identity import router as identity_router
from app.modules.instruments import router as instruments_router
from app.modules.limits import router as limits_router
from app.modules.multipliers import router as multipliers_router
from app.modules.payments import router as payments_router
from app.modules.pricing import router as pricing_router
from app.modules.reconciliation import router as reconciliation_router
from app.modules.redemption import router as redemption_router
from app.modules.roles import router as roles_router
from app.modules.rules import router as rules_router
from app.modules.segments import router as segments_router
from app.modules.services import router as services_router
from app.modules.step_up import router as step_up_router
from app.modules.tenants import router as tenants_router
from app.modules.treasury import router as treasury_router
from app.shared.exceptions import AppHTTPException

# Tag descriptions surfaced in /docs and the exported partner spec (Epic 14 S6).
_OPENAPI_TAGS = [
    {
        "name": "external",
        "description": (
            "Partner-facing API. Authenticate with `X-Sasai-Api-Key` (your "
            "public key id) plus `X-Sasai-Signature` — an HMAC-SHA256 over "
            "`{unix_ts}.{raw_body}` using your key secret, formatted "
            "`t=<unix_ts>,v1=<hex>` (300-second replay window). The tenant is "
            "derived from the key, never the body. Writes require an "
            "`Idempotency-Key` header; a retry that collides with an existing "
            "identifier returns the existing user (HTTP 200)."
        ),
    },
    {
        "name": "api-keys",
        "description": (
            "Admin management of external-API keys (platform-admin). The key "
            "secret is returned once at creation and only stored encrypted."
        ),
    },
]

app = FastAPI(
    title="Sasai Wallet & Rewards Platform",
    version="0.1.0",
    description=(
        "Backend API. See docs/05-technical-architecture.md for the full "
        "surface. Phase A endpoints are TEST-ONLY (no auth); Phase 2 adds "
        "Keycloak gating."
    ),
    openapi_tags=_OPENAPI_TAGS,
)


@app.exception_handler(AppHTTPException)
async def app_exception_handler(request: Request, exc: AppHTTPException) -> JSONResponse:
    """Render AppHTTPException as {error_code, message}.

    The FastAPI default would wrap our `detail` dict under `{"detail": {...}}`;
    we want the dict at the top level for cleaner API consumption.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is running."""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    """Top-level metadata endpoint."""
    return {
        "name": "Sasai Wallet & Rewards Platform",
        "version": "0.1.0",
        "docs": "/docs",
    }


# Register module routers.
app.include_router(identity_router)
app.include_router(accounts_router)
app.include_router(payments_router)
app.include_router(rules_router)
app.include_router(events_router)
app.include_router(external_router)
app.include_router(redemption_router)
app.include_router(catalog_router)
app.include_router(reconciliation_router)
app.include_router(roles_router)
app.include_router(tenants_router)
app.include_router(api_keys_router)
# Phase G — money controls
app.include_router(budgets_router)
app.include_router(limits_router)
app.include_router(pricing_router)
app.include_router(step_up_router)
app.include_router(treasury_router)
app.include_router(segments_router)
app.include_router(multipliers_router)
# Phase 2 — services catalog
app.include_router(services_router)
# Phase 3 — instruments catalog
app.include_router(instruments_router)
