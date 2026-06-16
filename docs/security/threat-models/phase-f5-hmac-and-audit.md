# Threat Model — Phase F.5 HMAC Verification + Audit Log Coverage

> **Date:** 2026-06-15
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0495 · NFR-0160, NFR-0210, NFR-0250, NFR-0260
> **Code reference:** `app/auth/hmac.py`, `app/modules/redemption/router.py`, `app/modules/events/service.py`, `app/modules/audit/service.py`
> **Linear:** WAL-48 · WAL-49

---

## 1. What this phase delivers

Phase F.4 closed the spoofing risks for **first-party** clients (admin app
and mobile app). Phase F.5 closes them for **third-party callbacks**:

- **WAL-48** — HMAC-SHA256 verification on every external callback / event:
  - Redemption provider success/fail callbacks
  - External event source Kafka payloads (the optional `shared_secret`
    column on `external_event_sources` becomes enforced when set)
- **WAL-49** — `audit_log` writes on every state-changing endpoint. Phase
  E.1 only wrote audit entries from reconciliation; F.5 generalises it.

### Endpoints / surfaces affected

| Surface | Change |
|---|---|
| `POST /api/v1/redemption/{id}/callback` | **New** — HMAC-gated provider callback (replaces admin-only `/confirm` + `/fail` for production traffic) |
| `POST /api/v1/redemption/{id}/confirm`  | Admin-only operator override (kept) |
| `POST /api/v1/redemption/{id}/fail`     | Admin-only operator override (kept) |
| Kafka consumer of `wallet.events.external` | Enforces HMAC when `source.shared_secret` is set |
| All state-changing endpoints | Now write `audit_log` entries |

## 2. Wire format (HMAC)

Stripe-style canonical string. Avoids ambiguity around JSON key ordering or
unicode normalisation:

```
canonical_string = "{timestamp_epoch_seconds}.{raw_body_bytes_utf8}"
signature        = hex(HMAC_SHA256(shared_secret, canonical_string))
```

The caller sets a single header:

```
X-Sasai-Signature: t=1718473200,v1=4e3a...
```

- `t=` is integer seconds since epoch UTC.
- `v1=` is the lowercase hex digest of HMAC-SHA256.
- Multiple `v1=` values may be present (comma-separated within the same
  header value) during secret rotation. Verification passes if ANY `v1`
  matches the current secret.

**Replay window:** `|now - t| <= 300` seconds. Outside that window → reject.

**Constant-time comparison:** `hmac.compare_digest`, not `==`.

## 3. Where the raw body matters

Pydantic parsing rewrites JSON whitespace and key order, so we MUST verify
against the raw request body bytes before any deserialisation. The
provider-callback router reads `await request.body()` first, then verifies,
then parses.

For Kafka events: the consumer receives the raw payload bytes from the
broker — verify against those bytes before passing to `process_external_event`.

## 4. STRIDE delta

| ID | Category | Threat | Mitigation |
|---|---|---|---|
| F5-S-1 | Spoofing | Attacker posts fake `POST /redemption/{id}/callback` claiming a redemption succeeded | HMAC verify against `provider.shared_secret`; unmatched → 401 + audit entry |
| F5-S-2 | Spoofing | Attacker posts fake Kafka event claiming a reward should be issued | HMAC verify against `source.shared_secret`; if secret set and verify fails → REJECTED + audit |
| F5-T-1 | Tampering | Attacker replays a previously-valid callback (e.g. to confirm a redemption that was later reversed) | Timestamp ≤ 5min replay window; out-of-window → reject |
| F5-T-2 | Tampering | Attacker mutates the body (e.g. changes points_amount) while keeping the timestamp | HMAC is computed over the body — any mutation invalidates the signature |
| F5-R-1 | Repudiation | Admin claims they never approved a config change | `audit_log` records actor_id (Keycloak sub), action, before/after state, IP, timestamp. Immutable (no UPDATE/DELETE) |
| F5-I-1 | Info disclosure | `shared_secret` leaks from logs / DB | Never logged, never in API responses; column is TEXT (not encrypted at rest in Phase 1 — see residual risks). PII-masking helpers apply |
| F5-D-1 | DoS | Attacker spams `/callback` with bogus signatures to burn CPU | HMAC verification is O(body_bytes). For 10KB bodies this is < 1ms. No additional rate limit in Phase 1; Phase G adds rate limit |
| F5-E-1 | Elevation | Provider with active callback can also call the admin `/confirm` if their HMAC is leaked + an admin token is stolen | Compound — needs both. Separate concern from F.5 |

## 5. Audit log coverage

After F.5, every endpoint that writes to the DB also appends an
`audit_log` row. Convention:

| Action | actor_type | actor_id | entity_type | Notes |
|---|---|---|---|---|
| `p2p.transferred` | user | `<user_uuid>` | transaction | After commit |
| `redemption.initiated` | user | `<user_uuid>` | redemption | After commit |
| `redemption.confirmed.by_provider` | system | `provider:<provider_uuid>` | redemption | Triggered by `/callback` |
| `redemption.failed.by_provider` | system | `provider:<provider_uuid>` | redemption | Triggered by `/callback` |
| `redemption.confirmed.by_admin` | admin | `<keycloak_sub>` | redemption | Triggered by `/confirm` override |
| `redemption.failed.by_admin` | admin | `<keycloak_sub>` | redemption | Triggered by `/fail` override |
| `redemption.callback.rejected` | system | `provider:<provider_uuid>?` | redemption | When HMAC verify fails |
| `provider.registered` | admin | `<keycloak_sub>` | redemption_provider | |
| `rule.created` | admin | `<keycloak_sub>` | rule | |
| `event_source.registered` | admin | `<keycloak_sub>` | external_event_source | |
| `event.rejected.integrity_failed` | system | `source:<source_key>` | external_event | When source HMAC verify fails |
| `user.registered.by_admin` | admin | `<keycloak_sub>` | user | Direct registration (not OTP flow) |
| `role.assigned` | admin | `<keycloak_sub>` | user_role | **Deferred to F.5.1** — small mechanical pass; pattern identical to rules.created |
| `role.removed` | admin | `<keycloak_sub>` | user_role | Deferred to F.5.1 |
| `role.permission.set` | admin | `<keycloak_sub>` | role_permission | Deferred to F.5.1 |
| `recon.*` | system | system | redemption | Already wired in Phase E.1 |

`actor_type='system'` covers both jobs and verified third-party callbacks
— the `actor_id` distinguishes them via prefix (`provider:`, `source:`).
That avoids a CHECK-constraint migration on `audit_log.actor_type`.

## 6. Residual risks accepted for F.5

- **`shared_secret` at rest** stored as plaintext TEXT. Phase 1 accepts
  this because the DB is internal-network only; production hardening adds
  pgcrypto column encryption (Phase 2). Mitigation: rotate secrets when a
  DB dump is suspected leaked.
- **No replay-id store.** Two distinct callbacks with the same body +
  same timestamp + same signature would both verify. For redemption this
  is mitigated by the redemption status transition guard (PENDING → terminal
  is one-way), so a replay of an old confirm/fail on a now-terminal
  redemption no-ops. For event ingestion, the existing dedup index on
  `event_ingestion_log(source_key, external_event_id)` blocks duplicates.
- **No revocation list for compromised secrets.** Rotation = update the
  column + redeploy. Phase G adds versioned secrets (`secret:v1`, `secret:v2`).
- **No mutual TLS yet.** HMAC is the only proof-of-origin. mTLS adds
  defence-in-depth and is on the Phase 2 roadmap.

## 7. Test scenarios

For `POST /redemption/{id}/callback`:
- Valid HMAC + recent timestamp → 200, redemption transitions
- Valid HMAC + timestamp older than 5 min → 401 `signature_timestamp_skew`
- Tampered body (one char changed) → 401 `invalid_signature`
- Missing `X-Sasai-Signature` header → 401 `signature_missing`
- Provider has no `shared_secret` configured → 401 `signature_not_configured`
- Outcome=completed but redemption already COMPLETED → 409 (no-op replay safety)
- Cross-tenant redemption_id → 404

For `audit_log`:
- After each state-change endpoint, a matching row exists with the right
  actor / entity / before+after states.
- audit_log entries cannot be deleted (immutability test is the
  `tests/invariants/` set).

## 8. Sign-off

- [x] STRIDE pass complete
- [x] HMAC scheme documented (canonical string, header format, replay)
- [x] Audit action vocabulary enumerated
- [x] Residual risks accepted and tracked
- Reviewed by: security agent (inline) on 2026-06-15
