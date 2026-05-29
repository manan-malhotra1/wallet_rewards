# Threat Model — Phase F.1 Keycloak Admin JWT Validation

> **Date:** 2026-05-29
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0100 · NFR-0170, NFR-0180, NFR-0210, NFR-0260
> **Code reference:** `backend/app/auth/`, `backend/app/dependencies.py`

---

## 1. What this phase delivers

The first layer of real auth: every request to an admin endpoint must carry
a valid Keycloak JWT. F.1 is the *infrastructure* for auth — Phase F.4 applies
it broadly to existing endpoints.

Scope (F.1 only):
- `KeycloakClient` — fetches and caches the realm's JWKS (24-hour TTL).
- `verify_jwt()` — validates signature, issuer, expiry; rejects `alg=none`.
- `get_current_admin()` FastAPI dependency — extracts a typed `AdminPrincipal`
  (id, username, roles) from the validated token.
- `require_admin_role(role)` — dependency factory for role-gating endpoints.
- Applied to ALL `/api/v1/reconciliation/*` endpoints as the pilot.
- Bootstrap script adds a test admin user (`admin-test`) with the
  `platform-admin` realm role so the demo + tests can produce real tokens.

Deferred to later F sub-phases:
- PIN/OTP user-side auth (F.2)
- Per-user platform roles (F.3 — Module 7)
- Remove test-only body params on other endpoints (F.4)
- HMAC on provider callbacks (F.5)
- Audit-log writes from auth events (F.5)

## 2. Data flow

```
[Admin client]
  Authorization: Bearer eyJ...
       |
       v
[FastAPI route — Depends(require_admin_role("platform-admin"))]
       |
       v
[get_current_admin]
   1. Extract "Bearer <token>" from Authorization header
   2. Decode unverified header — read kid + alg
   3. Reject alg='none' / unknown
   4. KeycloakClient.get_public_key(kid)  — JWKS cache hit, else fetch
   5. jose.jwt.decode — verify signature + exp + iss
   6. Build AdminPrincipal from claims (sub, realm_access.roles, ...)
       |
       v
[require_admin_role checks principal.roles]
       |
       v
[Route handler runs with `admin: AdminPrincipal`]
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption (F.1) |
|---|---|---|
| HTTP → API | Authorization header | Bearer prefix required; raw token treated as untrusted until verified |
| API → Keycloak JWKS | HTTPS GET | TLS verification on. In local dev we accept HTTP because Keycloak runs on `http://localhost:8080` — flagged as accepted residual for local dev only |
| Verified JWT → AdminPrincipal | Claims trusted only after `verify_jwt` succeeds | iss, exp, signature checked; aud check deferred to F.4 when we know which clients matter |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Attacker presents `alg: none` token | High | Critical | Explicit rejection in `verify_jwt` — algorithm whitelist `["RS256"]` only | mitigated |
| S-2 | Spoofing | Attacker presents token signed with their own key + matching `kid` | Low | Critical | We refetch JWKS on kid miss (one chance), and verify against Keycloak's public key — attacker can't impersonate without Keycloak's private key | mitigated |
| S-3 | Spoofing | Attacker presents another user's stolen token (replay) | Med | High | `exp` check (default 5 min for Keycloak access tokens); short-lived tokens limit blast radius. Token revocation list deferred to F.2 | accepted (short-lived) |
| T-1 | Tampering | Modify claims in the JWT payload | High (attempted) | Critical | Signature verification catches any payload modification | mitigated |
| T-2 | Tampering | Modify `kid` in header to point to a self-controlled key | Med | Critical | JWKS cache only contains Keycloak-issued keys; unknown kid → 401 | mitigated |
| R-1 | Repudiation | Admin denies an action | Med | Med | `sub` extracted from token; F.5 wires audit_log writes with `actor_id=principal.id` | partial (audit wiring in F.5) |
| I-1 | Info disclosure | JWT contains PII | Low | Med | Keycloak tokens carry user identifiers (sub, preferred_username); we never log the full token; we mask `preferred_username` if it's email-like | mitigated by convention |
| I-2 | Info disclosure | JWKS URL exposes more than needed | Low | Low | JWKS is a public endpoint by design (anyone can verify signatures) | n/a |
| D-1 | DoS | Spam unsigned tokens | Med | Low | Verification fails fast (header decode, alg check); rate limit in Phase G | accepted |
| D-2 | DoS | Force JWKS refetch by sending bad kids | Med | Med | Limit JWKS refetches to once per minute regardless of misses (cache-floor TTL); excessive misses logged | mitigated |
| E-1 | Elevation | Caller without `platform-admin` role hits a privileged endpoint | High | Critical | `require_admin_role(role)` checks the claim before any handler logic runs. Returns 403 `insufficient_role` | mitigated |
| E-2 | Elevation | Claim payload injected with extra roles | High (attempted) | Critical | Same as T-1 — signature verification catches it | mitigated |

## 5. Project-specific test scenarios (handed to `automation-testing`)

1. **Valid token + correct role** → 200 (happy path, in-memory test keypair).
2. **Missing Authorization header** → 401 `missing_token`.
3. **Wrong prefix (not "Bearer")** → 401 `invalid_token_format`.
4. **`alg: none` token** → 401 `invalid_algorithm`.
5. **Tampered payload** → 401 `invalid_token`.
6. **Token signed by wrong key** → 401 `invalid_token`.
7. **Expired token (`exp` in past)** → 401 `token_expired`.
8. **Issuer mismatch** → 401 `invalid_issuer`.
9. **Unknown `kid` (forces refetch, still missing)** → 401 `invalid_token`.
10. **Role missing** → 403 `insufficient_role`.
11. **JWKS cached** → second request doesn't refetch (counter-based test).
12. **JWKS refetch on cache expiry** → forced expiry triggers HTTPS GET.

## 6. Residual risks accepted for F.1

- **Keycloak runs over HTTP locally.** Documented; production must enforce
  HTTPS to satisfy NFR-0260.
- **No token revocation list.** Logout doesn't invalidate already-issued tokens
  — they expire normally. Acceptable for short-lived access tokens.
- **`aud` claim not verified.** Different clients in the same realm can each
  obtain tokens; F.1 trusts the realm. F.4 will narrow to specific audiences
  once we know which clients call which endpoints.
- **No audit log writes yet.** Admin actions are auth-gated but not yet
  recorded with the admin's identity. F.5 wires this in.

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Regression test list handed to automation-testing
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-29
