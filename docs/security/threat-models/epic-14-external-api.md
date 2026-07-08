# Threat Model — Epic 14 External Partner API

> **Date:** 2026-07-08
> **Reviewer:** security agent (adversarial VAPT — STRIDE + OWASP API Top 10 2023)
> **PRD reference:** Pay-PRD-0010, 0050, 0200 · NFR-0170, NFR-0210, NFR-0220, NFR-0260
> **Code reference:** `app/auth/{api_key,hmac,secret_box,rate_limit}.py`,
> `app/modules/external/{router,schemas}.py`,
> `app/modules/api_keys/{router,service,schemas}.py`,
> `app/shared/models/api_keys.py`, `alembic/versions/20260708_0023_*.py`
> **Scope commits:** 5b9bad4 → 4ef7c91 (on `main`)

---

## 1. What this feature does

A third-party partner is issued a per-tenant credential — a public `key_id`
(`sak_…`) plus a high-entropy secret shown exactly once. The partner calls
`POST /api/v1/external/users` with `X-Sasai-Api-Key: <key_id>` and
`X-Sasai-Signature: t=<unix>,v1=<hex>` (HMAC-SHA256 over `{t}.{raw_body}`,
300-second replay window). The server resolves the key → tenant, verifies the
signature against the Fernet-decrypted secret, per-key rate-limits, then
creates a user in **the key's tenant** by reusing `identity.create_user`.
Platform-admins mint / list / revoke keys via `/api/v1/api-keys`.

## 2. Data flow

```
[Partner backend]
  │  POST /api/v1/external/users
  │  X-Sasai-Api-Key: sak_...        (public)
  │  X-Sasai-Signature: t=..,v1=..   (HMAC over {t}.{raw_body})
  │  Idempotency-Key: ...            (REQUIRED — but currently unused, M1)
  │  body: {identifiers[], profile?, user_type?, parent_user_id?, verified?}
  ▼
[require_api_key dependency]  app/auth/api_key.py
  │  1. read raw body (await request.body())  ← unbounded, pre-auth (M3)
  │  2. SELECT api_keys WHERE key_id=? AND status='active'
  │       └─ miss → ApiKeyInvalid (401)         ← different code path than 3 (M2)
  │  3. decrypt_secret(Fernet)  → verify_signature(300s window)
  │       └─ fail → signature_* (401)           ← reveals key_id is valid (M2)
  │  4. consume_api_key_quota(key_id)  ← POST-auth only; probes not throttled (M3)
  ▼
[create_external_user]  app/modules/external/router.py
  │  tenant_id = principal.tenant_id  (from key — NOT body ✓)
  │  user_type / parent_user_id / verified taken from BODY (H1)
  ▼
[identity.create_user]  → DB commit → UserOut
```

## 3. Trust boundaries

| Boundary | What crosses it | Trust assumption | Reality |
|---|---|---|---|
| Partner → API | key_id + HMAC signature + body | Key proves tenant; HMAC proves integrity + origin | Holds for tenant scoping; body carries privilege-relevant fields the partner should not set (H1) |
| API → secret-at-rest | Fernet token | Secret recoverable only with `SECRET_KEY` | Single deterministic key; leak = full forge, rotation = outage (M5) |
| API → DB | ORM `select`/`insert` | tenant_id from key | ✓ correct |
| Admin → api-keys | Keycloak JWT (platform-admin) | Global admin mints for any tenant | ✓ intended; large blast radius (residual) |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation / Status |
|---|---|---|---|---|---|
| S-1 | Spoofing | Forge a request without the secret | Low | High | HMAC-SHA256 + constant-time compare — **fixed** |
| S-2 | Spoofing | Reuse/guess a `key_id` | Low | Med | 144-bit `key_id`; but valid-key oracle via error code (**M2, open**) |
| T-1 | Tampering | Mutate body after signing | Low | High | HMAC covers raw body — **fixed** |
| T-2 | Tampering | Set `tenant_id` via body to write cross-tenant | Low | High | No `tenant_id` field; tenant from key — **fixed** |
| T-3 | Tampering | Set privilege fields (`user_type`, `verified`, `parent_user_id`) via body | High | High | **Open — H1** (mass assignment / BOPLA) |
| R-1 | Repudiation | Partner denies creating a user | Med | Med | `api_key.created`/`revoked` audited; **user-create via external key writes no audit row** (partial — see residual) |
| I-1 | Info disclosure | Secret leaks via list / logs / audit | Low | High | Returned once; never in list/audit/logs — **fixed** |
| I-2 | Info disclosure | Enumerate valid `key_id`s | Low | Low | Error-code + timing oracle (**M2, open**); 144-bit entropy limits blast |
| I-3 | Info disclosure | Partner spec inventories internal API | Med | Low | Exported spec dumps all component schemas (**L1, open**) |
| D-1 | DoS | Unauthenticated flood / huge body before auth | Med | Med | Rate limit is post-auth; no body cap (**M3, open**) |
| D-2 | DoS | Giant `identifiers[]` in one authed call | Med | Med | No `max_length` on list (**M4, open**) |
| D-3 | DoS/Avail | `SECRET_KEY` rotation bricks every key | Low | High | Deterministic single Fernet key, decrypt 500s (**M5, open**) |
| E-1 | Elevation | Partner escapes its tenant | Low | High | Tenant from key everywhere — **fixed** |
| E-2 | Elevation | Non-admin mints/lists keys | Low | High | All admin routes `require_admin_role('platform-admin')` — **fixed** |

## 5. Findings (severity-ranked — full detail in the VAPT report)

| ID | Sev | Title | File | OWASP |
|---|---|---|---|---|
| H1 | HIGH | Partner mass-assigns `user_type` / `verified` / `parent_user_id` | `external/schemas.py:24-27` | API3 |
| M1 | MED | `Idempotency-Key` required but ignored; idempotency is identifier-based | `external/router.py:48` | API6 |
| M2 | MED | Valid-`key_id` enumeration oracle (error code + timing) | `auth/api_key.py:78-82` | API2 |
| M3 | MED | Rate limit is post-auth; unbounded pre-auth body read | `auth/api_key.py:103,112` | API4 |
| M4 | MED | `identifiers[]` has no maximum length | `external/schemas.py:24` | API4 |
| M5 | MED | Deterministic single Fernet key — no rotation, decrypt→500 | `auth/secret_box.py:29,45` | API8 |
| L1 | LOW | Exported partner spec dumps full internal schema catalog | `docs/api/external-openapi.json` | API9 |
| L2 | LOW | Fixed-window limiter allows ~2× boundary burst | `auth/rate_limit.py:62-77` | API4 |
| L3 | LOW | Signed payload not bound to method/path/key_id (latent) | `auth/hmac.py:77` | API2 |

### 5.1 Remediation status (2026-07-08, Epic 14)

| Finding | Status |
|---|---|
| **H1** | **Fixed** — the external schema no longer accepts `user_type`/`parent_user_id`; identifiers use `ExternalIdentifierIn` (no `verified`); the router forces `user_type="consumer"`, `parent_user_id=None`, and `verified=False`. Regression test `test_partner_cannot_mass_assign_privileged_fields`. |
| **M4** | **Fixed** — `identifiers` capped at `max_length=10`. |
| **M5** | **Partially fixed** — a decrypt failure now maps to `ApiKeyInvalid` (401) instead of an uncaught 500. `MultiFernet` key rotation + `SECRET_KEY` length validation remain deferred hardening. |
| M1, M2, M3, L1–L3 | **Deferred** — triaged as follow-up hardening (see §6). None affect the current internal state; H1 was the partner-exposure blocker and is closed. |

## 6. Residual risks (accepted / to confirm)

- **Global-admin key minting.** A single platform-admin token can mint a
  partner key for **any** tenant. Intended global-admin model, but the blast
  radius of one stolen admin token is every tenant's partner surface. Accepted
  for Phase 1; revisit with per-tenant admin scoping in Phase 2.
- **HMAC replay window (300s) with no nonce store.** A captured request can be
  replayed within 300s. For `POST /external/users` this is **incidentally**
  neutralised by identifier uniqueness (replay → existing user, 200) — it is
  *not* a property of the auth layer. Any future non-idempotent endpoint that
  reuses `require_api_key` would be replayable. Tie anti-replay to a real,
  enforced `Idempotency-Key` (M1) before adding such endpoints.
- **No audit row for external user creation.** `create_user` only writes an
  audit entry when an `admin` principal is passed; the external path passes
  none, so partner-driven user creation leaves no `audit_log` trail (only
  `api_keys.last_used_at` moves). Contradicts NFR-0250 spirit for a
  state-changing partner action. Recommend a `user.registered.by_partner`
  system-audit row (actor_id `apikey:<key_id>`). Coordinate with `compliance`.
- **`SECRET_KEY` has no entropy/length validation** in `config.Settings`.
  Document + enforce a ≥ 32-byte random value; a weak value weakens every
  API-key secret at rest (offline brute-force if ciphertext leaks).

## 7. Required regression tests (hand to `automation-testing`)

- `test_external_create_rejects_privileged_user_type` — partner cannot create
  `agent`/`super_agent`/`merchant`/`head_merchant` (or asserts the allowed set).
- `test_external_create_cannot_set_verified_true` — `verified` is server-forced.
- `test_external_auth_failures_are_indistinguishable` — unknown key, revoked
  key, and valid-key-bad-signature all return the **same** 401 `error_code`.
- `test_external_create_rejects_oversized_identifier_list` — `identifiers[]`
  above the cap → 422.
- `test_external_create_rejects_oversized_body` — body over the max → 413/422
  before signature work.
- `test_external_idempotency_key_dedupes` — same `Idempotency-Key` + different
  body does not create a second user (once M1 is fixed).
- `test_secret_box_rotation_with_multifernet` — a secret encrypted under key v1
  still decrypts after v2 is prepended (once M5 is fixed).
- `test_external_create_writes_audit_row` — partner user-create leaves an
  `audit_log` entry with no secret in it.

## 8. Sign-off

- [x] STRIDE pass complete
- [x] OWASP API Top 10 (2023) pass complete
- [x] Fintech-specific scenarios (tenant isolation, replay, enumeration, secret disclosure) exercised against code
- [x] H1 mitigated (external schema hardened + values forced server-side; regression test added) — 2026-07-08
- [x] M4 fixed (identifier cap); M5 partially fixed (decrypt → 401). M1, M2, M3, M5-rotation, L1–L3 triaged as deferred hardening (§5.1, §6)
- Reviewed by: security agent (adversarial) on 2026-07-08
