# Threat Model — Phase F.4 Remove Test-Only Params, Gate Every Endpoint

> **Date:** 2026-05-31
> **Reviewer:** security agent (inline)
> **PRD reference:** Closes residual risks carried from Phases A–E
> **Code reference:** every `app/modules/*/router.py` + schemas
> **Linear:** WAL-47

---

## 1. What this phase delivers

This is the **security closeout** for Phases A–E. Until F.4, almost every
endpoint accepted `tenant_id` and (for user-facing endpoints) `sender_user_id`
/ `user_id` in the request body — meaning an unauthenticated caller could
spoof anyone's identity and tenant. The threat models for A–E all flagged
this as an accepted residual risk pending F.4.

After F.4:
- **Every** endpoint requires auth (Keycloak admin JWT or session token).
- **No** endpoint accepts identity-defining IDs in the request body.
- All `(test-only)` OpenAPI tags removed.

### Routing decisions per endpoint

| Endpoint | Auth | Notes |
|---|---|---|
| `POST /identity/users` | Admin (platform-admin) | Phase A test-only registration helper |
| `GET /identity/resolve/*` | Admin (platform-admin or finance-reviewer) | Operator lookup |
| `POST /identity/otp/send` | Public | Auth flow itself |
| `POST /identity/otp/verify` | Public | Auth flow itself |
| `POST /identity/pin/set` | Public (consumes registration_token) | Auth flow itself |
| `POST /identity/auth/pin` | Public | Auth flow itself |
| `POST /identity/auth/logout` | User (or no-op) | Self-invalidate |
| `POST /accounts` | Admin (platform-admin) | Account creation is admin-only |
| `GET /accounts/{id}/balance` | Admin (read-any) | User self-read via /catalog/me/summary instead |
| `POST /payments/p2p` | **User** | Sender + tenant from session |
| `POST /events/sources` | Admin (platform-admin) | Source registration |
| `POST /events/external` | Admin (platform-admin) | F.5 will swap to HMAC for production callbacks |
| `POST /rules` | Admin (platform-admin) | Rule CRUD |
| `GET /rules` | Admin (platform-admin or finance-reviewer) | |
| `POST /redemption/providers` | Admin (platform-admin) | Provider config |
| `POST /redemption/initiate` | **User** | User from session |
| `POST /redemption/{id}/confirm` | Admin (platform-admin) | F.5 swaps to HMAC for real provider callbacks |
| `POST /redemption/{id}/fail` | Admin (platform-admin) | F.5 swaps to HMAC |
| `GET /redemption/{id}` | Admin (read-any) | User self-read via catalog |
| `GET /catalog/me/summary` | **User** | Was `{user_id}` — now implicit |
| `GET /catalog/me/redemption-history` | **User** | |
| `GET /catalog/me/points-history` | **User** | |
| `/reconciliation/*` | Admin (gated in F.1) | No change |
| `/roles/*` | Admin (gated in F.3) | No change |

## 2. Data flow change

### Before (Phase B example)

```
[Anyone with the URL] → POST /payments/p2p
   body: { tenant_id: "...", sender_user_id: "<anyone_id>", ... }
                                            ↑ SPOOFABLE
   → Service trusts body → ledger writes against the spoofed user
```

### After (Phase F.4)

```
[User app] → POST /payments/p2p
   Authorization: Bearer <session_token>
   body: { recipient: {...}, amount: ..., currency: ... }
                                ↑ no IDs
   → get_current_user resolves session → UserPrincipal(id, tenant_id, channel)
   → Service uses principal.id as sender_user_id, principal.tenant_id as tenant
   → Cannot spoof
```

## 3. STRIDE — what's actually new

This phase **resolves** rather than adds threats — it closes the spoofing
gap that every prior threat model flagged. Net STRIDE delta:

| ID | Category | Threat | Status After F.4 |
|---|---|---|---|
| Carried — Phase A S-1 | Spoofing | Caller fakes `tenant_id` in identity request body | **CLOSED** — admin gate; admin token comes from Keycloak (trusted realm) |
| Carried — Phase B S-1 | Spoofing | Caller fakes `sender_user_id` in /p2p | **CLOSED** — sender from session_token |
| Carried — Phase D S-1 | Spoofing | Caller fakes `user_id` in /redemption/initiate | **CLOSED** — user from session_token |
| Carried — Phase D I-1 | Info disclosure | Redemption history queryable for any user_id | **CLOSED** — `/me` only |
| Carried — Phase E.1 S-1 | Spoofing | Operator identity spoofed in /resolve | **CLOSED** — admin gate |
| Carried — Phase E.1 E-1 | Elevation | Support-agent role manually resolves redemptions | Already F.1 — confirm/fail need platform-admin |
| New — F.4 T-1 | Tampering | Logout sent with another user's session_token | Already F.2 — session_token is opaque random; possession = ownership; mitigated by HTTPS in transit |

## 4. Test scenarios delivered

For each gated endpoint:
- **Auth missing**: 401 `invalid_authorization_header` (admin) / `invalid_session` (user)
- **Wrong principal type**: user token on admin endpoint → 401 invalid_token (sigfail); admin token on user endpoint → 401 invalid_session
- **Insufficient role**: admin without `platform-admin` → 403 `insufficient_role`
- **Correct auth**: 200/201 happy path

For schema changes:
- P2P body no longer accepts `tenant_id` / `sender_user_id` — Pydantic rejects extra fields (or silently ignores; we tighten with `model_config = ConfigDict(extra='forbid')` where it matters)
- Redemption initiate body similarly cleaned

Existing tests preserved:
- All 147 prior tests run with new auth fixtures (`user_auth_header_for_alice`, `admin_auth_header`)

## 5. Residual risks accepted for F.4

- **No CSRF protection** on user endpoints. Mobile API consumers are token-bearer; classic CSRF doesn't apply. If a browser SPA ever calls these endpoints directly, CSRF needs adding.
- **No replay protection** beyond TLS at the transport layer. Idempotency-Key handles same-request dedup, but a network attacker who captures a session_token can replay it within its TTL.
- **No rate limit on session_token validation**. A brute-forcer hitting `get_current_user` with random tokens gets rejected quickly but consumes CPU. Phase G or a separate rate-limit phase addresses this.
- **HMAC on provider callbacks still in F.5** — `/redemption/{id}/confirm` and `/fail` are still admin-gated in F.4. Real provider callbacks will use HMAC signatures.

## 6. Sign-off

- [x] STRIDE pass complete
- [x] Endpoint-by-endpoint auth decision documented
- [x] Test coverage strategy enumerated
- Reviewed by: security agent (inline) on 2026-05-31
