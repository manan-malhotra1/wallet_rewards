# Threat Model — Phase F.2 PIN/OTP User Auth + Redis Sessions

> **Date:** 2026-05-30
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0020, 0030, 0040 · NFR-0170, 0180, 0190, 0280
> **Code reference:** `backend/app/modules/identity/`, `backend/app/auth/`
> **Linear:** WAL-45

---

## 1. What this phase delivers

The end-user authentication flow. Phase F.1 gated **admin** endpoints with
Keycloak JWTs; F.2 gates **user** endpoints with a custom PIN/OTP flow that
issues opaque session tokens stored in Redis.

Endpoints (all on `/api/v1/identity/`):

- `POST /otp/send` — generates 6-digit OTP, bcrypt-hashes, stores in `otp_requests`, "delivers" (mocked: returned in response when `OTP_DEV_RETURN=true`, else logged for SMS gateway integration in a later phase).
- `POST /otp/verify` — verifies OTP against stored hash, marks `used_at`, returns short-lived `registration_token` (proof of phone ownership; 10-min TTL in Redis).
- `POST /pin/set` — requires `registration_token`; sets bcrypt-hashed PIN on the user row.
- `POST /auth/pin` — verifies PIN; on success returns opaque `session_token` (Redis TTL = 15 min mobile inactivity per NFR-0180); on failure logs to `auth_attempts` + enforces lockout after `PIN_MAX_ATTEMPTS`.
- `POST /auth/logout` — invalidates the session token.

New infrastructure:

- `app/auth/sessions.py` — Redis-backed opaque token store with TTL.
- `app/auth/hashing.py` — bcrypt wrappers for OTP and PIN.
- `app/auth/lockout.py` — tracks consecutive failed attempts; lockout in Redis with TTL.
- `app/auth/principals.py` — extended with `UserPrincipal` (id, tenant_id, phone, channel).
- `app/dependencies.py` — adds `get_current_user()` dependency.

Scope NOT in F.2:
- Real SMS gateway (deferred to a later phase — F.2 logs the OTP).
- USSD-channel session model (only mobile-app channel in F.2).
- Biometric unlock (Phase 2 per `mobile/.claude.md`).
- Concurrent-session invalidation across channels (NFR-0280 deferred to F.4 when other endpoints gate-check).

## 2. Data flow

```
[User mobile app]
    |
    |  POST /otp/send  { phone: "+27 82 555 0001" }
    v
[OTP service]
    1. resolve phone → user_id (or auto-register if first-time)
    2. generate 6-digit OTP via secrets
    3. bcrypt-hash, store row in otp_requests
    4. (mocked) "deliver" — return in body when OTP_DEV_RETURN=true
    |
    |  → 202 Accepted (OTP delivered to user's phone in prod)
    v

[User]
    |
    |  POST /otp/verify { phone, otp: "123456" }
    v
[OTP service]
    1. find latest unused, unexpired otp_request for phone
    2. bcrypt-verify the supplied OTP
    3. mark otp_requests.used_at
    4. generate registration_token (secrets.token_urlsafe), store in
       Redis with TTL=10min and value={user_id, phone, purpose}
    |
    |  → 200 { registration_token }
    v

[User]
    |
    |  POST /pin/set { registration_token, pin: "1234" }
    v
[PIN service]
    1. validate registration_token in Redis
    2. bcrypt-hash PIN, store on users.pin_hash
    3. invalidate registration_token (delete from Redis)
    |
    |  → 204 No Content
    v

[User wants to use app — later session]
    |
    |  POST /auth/pin { phone, pin: "1234" }
    v
[Auth service]
    1. check Redis lockout:<user_id> — if locked, 423
    2. resolve phone → user_id
    3. bcrypt-verify supplied PIN against users.pin_hash
    4. if FAIL:
         - increment Redis counter failed_attempts:<user_id> with 1h TTL
         - write auth_attempts row (success=false)
         - if counter >= PIN_MAX_ATTEMPTS: set lockout:<user_id> with TTL=PIN_LOCKOUT_MINUTES
         - return 401 invalid_credentials (or 423 account_locked when triggered)
    5. if SUCCESS:
         - reset failed_attempts counter
         - write auth_attempts row (success=true)
         - generate session_token, store in Redis with TTL=15min
         - return 200 { session_token, expires_in: 900 }
    |
    |  → 200 { session_token }
    v

[User on subsequent requests]
    |  GET /catalog/me/summary
    |  Authorization: Bearer <session_token>
    v
[get_current_user dependency]
    1. extract token from Authorization header
    2. look up session:<token> in Redis
    3. if found: build UserPrincipal, refresh TTL (sliding expiry)
    4. if not found: 401 invalid_session
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption |
|---|---|---|
| HTTP → API | Authorization header / request body | Pydantic validates. Phone resolved against `user_identifiers` (tenant-scoped). |
| API → Redis | Token + state lookups | Local Redis instance. TLS deferred to deployment phase. Redis must be private. |
| API → PostgreSQL | bcrypt hashes only | PIN/OTP never appear in plaintext outside the verifier function. |
| Service → response | session_token + registration_token | One-time bearer credentials. Never logged. Returned only in response body. |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Attacker submits another user's phone + tries to guess PIN | Med | High | Lockout after `PIN_MAX_ATTEMPTS` (5); 30-min Redis-based lockout window | mitigated |
| S-2 | Spoofing | Stolen session token replayed | Low | Critical | Opaque random tokens (32 bytes); 15-min TTL; logout invalidates immediately | mitigated |
| T-1 | Tampering | Modify OTP between send and verify | Low | Med | bcrypt one-way hash means tampering breaks comparison | mitigated |
| T-2 | Tampering | Skip OTP verification (forge a `registration_token`) | Med | High | Tokens are server-generated `secrets.token_urlsafe(32)` random; not derivable | mitigated |
| R-1 | Repudiation | User denies setting their PIN | Low | Low | `auth_attempts` records all PIN/OTP submissions with timestamp + IP | mitigated |
| I-1 | Info disclosure | OTP visible in app logs | High (if naive) | Critical | OTP NEVER logged. PIN NEVER logged. Tokens NEVER logged. (NFR-0170) — code review enforced | mitigated |
| I-2 | Info disclosure | OTP delivery channel hijacked (e.g. SIM-swap) | Med (real-world) | High | Out of scope for software — operational mitigations live elsewhere | accepted |
| I-3 | Info disclosure | Redis snapshot leak exposes session tokens | Low | High | Sessions in Redis only, not persisted to disk in dev (appendonly disabled). Production must encrypt Redis at rest. | accepted (Phase 1 / dev) |
| D-1 | DoS | Spam `/otp/send` to deplete SMS credits | High | Med | Rate limit per phone (1 OTP per 60s, 5 per hour) | mitigated |
| D-2 | DoS | Spam `/auth/pin` with wrong PINs | Med | Low | Lockout after `PIN_MAX_ATTEMPTS` consecutive fails | mitigated |
| E-1 | Elevation | User obtains session_token for a different user | Critical | Critical | Session_token value is the lookup key; collisions impossible at 32 bytes random | mitigated |
| E-2 | Elevation | Session token used for admin endpoints | High (attempt) | Critical | Admin endpoints use Keycloak JWT validation (Phase F.1); session tokens fail signature check. Separate paths. | mitigated |

## 5. Project-specific test scenarios

OTP send:
1. Happy path → 202; row in `otp_requests`; in dev mode response includes OTP
2. Same phone resend within 60s → 429 `otp_rate_limited`
3. Unknown tenant → 404
4. Unknown phone in tenant → auto-creates `users` + `user_identifiers` rows (registration path)

OTP verify:
5. Happy path → 200 with `registration_token`; `otp_requests.used_at` set
6. Wrong OTP → 401 `invalid_otp`; OTP NOT marked used; failed-attempt counter +1
7. Expired OTP (> 5 min) → 401 `otp_expired`
8. Already-used OTP → 401 `invalid_otp` (no enumeration leak)
9. Wrong phone → 401 (don't reveal whether the OTP itself was correct)

PIN set:
10. With valid registration_token → 204; `users.pin_hash` populated
11. With expired/missing registration_token → 401 `invalid_registration_token`
12. PIN too short (< 4) or too long (> 6) → 422
13. PIN already set → 409 `pin_already_set` (PIN reset is a different flow)

PIN auth:
14. Happy path → 200 with `session_token`
15. Wrong PIN → 401 `invalid_credentials`; `auth_attempts` row written
16. After `PIN_MAX_ATTEMPTS` wrong → next attempt → 423 `account_locked` for `PIN_LOCKOUT_MINUTES`
17. While locked, even a correct PIN → 423
18. Lockout expires → counter resets, login succeeds with correct PIN
19. User with no PIN set → 401 `pin_not_set`

get_current_user:
20. Valid session_token → request proceeds; UserPrincipal injected
21. Missing token → 401 `invalid_authorization_header`
22. Expired token (Redis TTL passed) → 401 `invalid_session`
23. Token format wrong (not Bearer) → 401
24. Logout invalidates token (next request → 401)

## 6. Residual risks accepted for F.2

- **SMS gateway not wired.** OTP is logged + (in dev) returned in response. Real delivery is a separate integration phase.
- **Redis runs on local-dev with no TLS.** Production must enforce TLS in transit (NFR-0260) and encryption at rest.
- **No cross-channel session invalidation** (NFR-0280). When USSD channel ships, opening a new mobile session must invalidate the USSD one. Tracked separately.
- **No biometric unlock** — out of Phase 1 scope.
- **Registration_token replay window** is 10 min. An attacker who steals it can call `/pin/set`. Accepted because it requires breaching the user's HTTPS session within 10 min of OTP verify.

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Test scenarios enumerated
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-30
