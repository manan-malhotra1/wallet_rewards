# Threat Model — Phase F.5 HMAC Verification + Audit Log Coverage

> **Date:** 2026-06-15
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0495 · NFR-0160, NFR-0210, NFR-0250, NFR-0260
> **Code reference:** `app/auth/hmac.py`, `app/modules/redemption/router.py`, `app/modules/events/service.py`, `app/modules/audit/service.py`
> **Linear:** WAL-48 · WAL-49

> ### ⚠ Correction — 2026-08-21
>
> A code read of the ingestion path found that **this document overstated a control that was
> never wired up.** The Kafka consumer (`scripts/run_consumer.py`) calls
> `process_external_event()` without `raw_body=` or `signature_header=` and never reads
> `msg.headers()`, so HMAC verification does **not** happen on the Kafka path — the only path
> that carries production traffic. A source with a secret rejects every message
> (`integrity_check_missing`); a source without one is accepted unverified. The signature gate
> works only on the HTTP routes (`/events/external`, `/events/sim-ingest`), which is where all
> its test coverage lives.
>
> Statements below that assert otherwise are struck through and annotated. Tracked as
> **Epic SEC** (SEC.1 / SEC.2) in [`docs/09-epics-and-stories.md`](../../09-epics-and-stories.md).
> Do not treat this phase's Kafka spoofing mitigation as in effect until SEC.1 and SEC.2 ship.

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
| Kafka consumer of `wallet.events.external` | ~~Enforces HMAC when `source.shared_secret` is set~~ — **NOT IMPLEMENTED.** The consumer never passes the raw bytes or the signature to the pipeline, so the check is inert here (SEC.1). |
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

> **⚠ Not implemented.** This describes the intent, not the code. The consumer
> discards the bytes after `json.loads` and forwards only the parsed model, so the
> pipeline receives `raw_body=None` and cannot verify anything. The fix is to carry
> `X-Sasai-Signature` as a Kafka **message header** and pass `msg.value()` through
> unparsed (SEC.1).

## 4. STRIDE delta

| ID | Category | Threat | Mitigation |
|---|---|---|---|
| F5-S-1 | Spoofing | Attacker posts fake `POST /redemption/{id}/callback` claiming a redemption succeeded | HMAC verify against `provider.shared_secret`; unmatched → 401 + audit entry |
| F5-S-2 | Spoofing | Attacker posts fake Kafka event claiming a reward should be issued | **⚠ OPEN — mitigation not in effect on the Kafka path.** The intended control (HMAC verify against `source.shared_secret`; verify fails → REJECTED + audit) holds only on the HTTP routes. On Kafka, a source registered without a secret — which the admin UI permits in one click — mints points on an unsigned message. See SEC.1 (wire the consumer) and SEC.2 (make the secret mandatory). |
| F5-T-1 | Tampering | Attacker replays a previously-valid callback (e.g. to confirm a redemption that was later reversed) | Timestamp ≤ 5min replay window; out-of-window → reject |
| F5-T-2 | Tampering | Attacker mutates the body (e.g. changes points_amount) while keeping the timestamp | HMAC is computed over the body — any mutation invalidates the signature |
| F5-R-1 | Repudiation | Admin claims they never approved a config change | `audit_log` records actor_id (Keycloak sub), action, before/after state, IP, timestamp. Immutable (no UPDATE/DELETE) |
| F5-I-1 | Info disclosure | `shared_secret` leaks from logs / DB | Never logged, never in API responses; column is Fernet-encrypted at rest as `shared_secret_encrypted` — this row previously said plaintext TEXT, which the code has not matched since Decision D3. PII-masking helpers apply |
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

- ~~**`shared_secret` at rest** stored as plaintext TEXT.~~ **Resolved and this
  entry was stale:** secrets are stored Fernet-encrypted in
  `external_event_sources.shared_secret_encrypted` (Decision D3) and decrypted only
  at verification time; an undecryptable secret is rejected, never skipped. The
  remaining gap is operational, not cryptographic — there is no way to rotate a
  secret from the admin UI (SEC.3).
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
- **⚠ NOT ACCEPTED — open critical finding (2026-08-21).** HMAC is not enforced on
  the Kafka path at all (SEC.1), and the signing secret is optional at source
  registration (SEC.2), so a registered `source_key` — an identifier that travels in
  every event payload and appears in logs — is the only control between a Kafka
  message and minted points. Points convert to fiat via internal redemption
  (Module 11b), so this is a money-loss path. Compounded by a broker running
  PLAINTEXT with no SASL and no ACLs (SEC.6). This is listed as open, not accepted:
  it is a defect against what this phase claimed to deliver.

## 7. Test scenarios

For `POST /redemption/{id}/callback`:
- Valid HMAC + recent timestamp → 200, redemption transitions
- Valid HMAC + timestamp older than 5 min → 401 `signature_timestamp_skew`
- Tampered body (one char changed) → 401 `invalid_signature`
- Missing `X-Sasai-Signature` header → 401 `signature_missing`
- Provider has no `shared_secret` configured → 401 `signature_not_configured`
- Outcome=completed but redemption already COMPLETED → 409 (no-op replay safety)
- Cross-tenant redemption_id → 404

For the Kafka consumer of `wallet.events.external` — **none of these exist today**;
HMAC is tested only on the HTTP routes. Required by SEC.1:
- Valid signature in the message header → PROCESSED, reward issued
- Forged / tampered payload → REJECTED `integrity_check_failed` + audit row
- Missing signature header → REJECTED `integrity_check_missing` + audit row
- Source registered with no secret → REJECTED (once SEC.2 removes the skip branch)

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
- **[ ] Kafka-path HMAC enforcement — sign-off WITHDRAWN 2026-08-21.** The control was
  documented and signed off but never wired into the consumer; see the correction
  banner at the top and Epic SEC.
