# Threat Model — Epic 17 Airtime Merchant Vertical

> **Date:** 2026-07-09
> **Reviewer:** security agent (adversarial VAPT — STRIDE + OWASP API Top 10 2023)
> **PRD reference:** Pay-PRD-0200 (idempotency), Pay-PRD-0220 (overdraft),
> Pay-PRD-0260 (orchestration order) · NFR-0130, NFR-0170, NFR-0210, NFR-0240, NFR-0250, NFR-0260
> **Code reference:** `app/modules/airtime/{router,service,schemas,provider}.py`,
> `app/shared/models/{merchant_profiles,airtime}.py`,
> `app/auth/{hmac,secret_box}.py`, `scripts/seed.py`,
> `alembic/versions/20260709_0024_airtime_merchant_vertical.py`
> **Scope commits:** dc45ce6 → 9b5928e (on `main`)

---

## 1. What this feature does

A user buys airtime. The service reserves funds as a PENDING double-entry
(DEBIT user `financial_wallet`, CREDIT the tenant's single active airtime
merchant's `airtime_merchant_holding` account, plus optional fee legs), COMMITS,
then calls the provider **after** the commit (NFR-0130). A fast terminal result
finalises in-request — `200` COMPLETED or `200` REVERSED-with-refund. A slow /
pending provider returns `202` and the recharge stays PENDING, later resolved by
an HMAC-verified provider callback (`POST /{id}/callback`) or a platform-admin
`POST /{id}/resolve`. Finalisation flips the parent transaction + its ledger
entries' `status` — never an UPDATE to a ledger row's money (ledger-invariants §1).

The merchant is a `user_type='merchant'` user with a `merchant_profiles` row
carrying a provisioning `mode` (`simulator` | `live`), non-secret
`provider_config`, and a Fernet-encrypted `callback_secret_encrypted`. v1 wires
only the simulator; `get_provider('live')` raises rather than moving real money.

## 2. Data flow

```
[Mobile / user session]
  │  POST /api/v1/airtime/recharge
  │  Authorization: session token  → get_current_user → (tenant_id, user_id)   ✓ never from body
  │  Idempotency-Key: <required>
  │  body: {msisdn, network, amount, currency, pin?}     ← ONLY these; status/user/tenant/ref NOT settable ✓
  ▼
[initiate_recharge]  service.py:178
  │  tenant exists → require_permission(airtime_recharge) → find active merchant
  │  idempotency fast-path (tenant, key) → existing recharge, no re-write
  │  find user wallet → get/create merchant holding → SELECT FOR UPDATE wallet   ✓ lock
  │  check_limits → wallet-send limits → step_up(PIN) → resolve fee
  │  OVERDRAFT: balance-reserved < amount+fee → 409  ← BEFORE any write, fee included ✓
  │  post_transaction(PENDING, [debit wallet, credit holding, +fee legs]) → COMMIT (internal)
  │  INSERT airtime_recharges(PENDING) → audit initiated (msisdn MASKED) → COMMIT
  ▼
[attempt_provision]  service.py:436   (AFTER commit — NFR-0130)
  │  if status != PENDING: return                     ← check-then-act, NO lock/claim (A1)
  │  provider.provision(recharge_id, msisdn, ...)     ← network I/O; re-callable per retry (A1)
  │  success → _apply_completed (200) │ failed → _apply_reversed+refund (200) │ pending → 202
  ▼
[POST /{id}/callback]  router.py:102   (NO auth header — HMAC is the auth)
  │  lookup recharge BY ID (global) → 404 if absent          ← existence oracle before auth (A4)
  │  find tenant's merchant → decrypt secret → verify_signature(RAW body, 300s window)
  │  parse body → status guard (PENDING?) → apply → audit → commit
  ▼
[POST /{id}/resolve]  router.py:126   require_admin_role('platform-admin'); tenant_id in body
```

## 3. Trust boundaries

| Boundary | What crosses it | Trust assumption | Reality |
|---|---|---|---|
| User → `/recharge` | session token + body | Buyer + tenant from token; body is data only | Holds — server sets tenant/user/status/ref; no mass-assignment (contrast Epic 14 H1) ✓ |
| User → `/{id}` (GET) | session token + recharge_id | Caller may read the recharge | Scoped by **tenant only, not owner** — any tenant user who learns a recharge_id reads its msisdn (A2) |
| Provider → `/callback` | raw body + `X-Sasai-Signature` | HMAC over `{t}.{body}` proves origin + integrity; secret is per-tenant merchant secret | Holds for tenant binding; but DB lookups + Fernet decrypt run pre-verify, no rate limit, unbounded body (A4) |
| Callback secret at rest | Fernet token | Recoverable only with `SECRET_KEY` | Single deterministic key; rotation bricks callbacks (A5). Seed plants a **public** dev secret; no prod rotation path (A3) |
| Admin → `/resolve` | Keycloak JWT (platform-admin) + `tenant_id` body | Global admin resolves any tenant | Intended; large blast radius (residual) |
| Service → provider | `provider_config` (endpoint etc.) | Config is operator-set, not user-set | True today (`live` raises). When live adapter lands, server-fetched URL → SSRF (residual) |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation / Status |
|---|---|---|---|---|---|
| S-1 | Spoofing | Forge a provider callback without the secret | Low | High | HMAC-SHA256 + constant-time compare, verified against the recharge's own tenant merchant secret — **mitigated** |
| S-2 | Spoofing | Settle a recharge using a *public* callback secret | Med | High | Seed plants `dev-airtime-callback-secret-...`; no prod secret-generation path (**A3, open**) |
| S-3 | Spoofing | Impersonate another buyer / set `user_id` via body | Low | High | tenant + user from session token; body ignores them — **mitigated** |
| T-1 | Tampering | Mutate callback body after signing | Low | High | HMAC covers raw body, verified before parse — **mitigated** |
| T-2 | Tampering | Mass-assign `status`/`provider_reference`/`tenant_id`/`verified` via recharge body | Low | High | Schema exposes only msisdn/network/amount/currency/pin; server sets the rest — **mitigated** (A7 nit: `extra` defaults to ignore, not forbid) |
| T-3 | Tampering | Race sync-attempt vs callback/resolve to overwrite a terminal state | Med | Med | Unguarded `status==PENDING` check; UPDATE has no `WHERE status='PENDING'` (**A1, open**) |
| T-4 | Tampering | Direct UPDATE of ledger money | Low | High | Only `status` flips on existing entries via parent txn; money columns immutable — **mitigated** |
| R-1 | Repudiation | User/admin/provider denies an action | Low | Low | initiated / completed / reversed / resolved all audited with actor + before/after — **mitigated** |
| I-1 | Info disclosure | Another user's msisdn (PII) read within a tenant | Med | Med | GET is tenant-scoped, not owner-scoped (**A2, open**); UUIDv4 id limits blast |
| I-2 | Info disclosure | Enumerate valid recharge_ids via callback error codes | Low | Low | 404 vs 422 vs 401 oracle before HMAC (**A4, open**); UUIDv4 (122-bit) limits it |
| I-3 | Info disclosure | Secret / PIN leaks via logs or audit | Low | High | No logging in module; PIN never stored; secret never logged; msisdn masked in audit — **mitigated** |
| D-1 | DoS | Unauthenticated callback flood: DB lookups + Fernet decrypt + unbounded body before auth | Med | Med | No rate limit, no body cap on `/callback` (**A4, open**) |
| D-2 | DoS/Avail | `SECRET_KEY` rotation makes every callback secret undecryptable | Low | Med | Single deterministic Fernet key; decrypt→401; forces admin-resolve (**A5, open**) |
| E-1 | Elevation | Buyer escapes tenant (wallet / holding / GET / resolve) | Low | High | Every domain query filters `tenant_id`; callback bound to recharge's own tenant secret — **mitigated** |
| E-2 | Elevation | Non-admin resolves a stuck recharge | Low | High | `/resolve` gated by `require_admin_role('platform-admin')` — **mitigated** |
| E-3 | Elevation/$$ | Same reservation triggers >1 provider vend (retry / pending re-poke) | Med | Med | `attempt_provision` re-callable while PENDING; no claim; provider dedupe not enforced (**A1, open**) |

## 5. Findings (severity-ranked)

| ID | Sev | Title | File:line | OWASP |
|---|---|---|---|---|
| A1 | MED | Unguarded `PENDING` check → double provider-vend + terminal-state overwrite (no row lock / conditional claim) | `airtime/service.py:450`, `466`, `376-385` | API6 |
| A2 | MED | `GET /airtime/{id}` scoped by tenant, not owner → intra-tenant BOLA leaks another user's msisdn (PII) | `airtime/service.py:512-525`, `airtime/router.py:91-99` | API1 |
| A3 | MED | Only merchant-creation path (seed) hardcodes + prints a public DEV callback secret; no prod onboarding / rotation path | `scripts/seed.py:510,566,572` | API2 / API8 |
| A4 | LOW | `/callback` unauthenticated-until-HMAC: DB lookups + Fernet decrypt + unbounded body before verify, no rate limit; 404/422/401 existence oracle | `airtime/router.py:102-123`, `airtime/service.py:558-573` | API4 / API2 |
| A5 | LOW | Single deterministic Fernet key (no MultiFernet) — `SECRET_KEY` rotation bricks every callback secret | `auth/secret_box.py:21-30`, `airtime/service.py:567-571` | API8 |
| A6 | LOW | Recharge-row INSERT doesn't catch `IntegrityError` to return the original; two-commit initiate can orphan a PENDING reservation on crash | `airtime/service.py:296-308,338` | API6 |
| A7 | INFO | Recharge schema uses default `extra='ignore'`; privileged fields are dropped (safe) but silently — prefer `extra='forbid'` | `airtime/schemas.py:13-26` | API3 |

### 5.1 Finding detail

**A1 — Unguarded PENDING check (concurrency).** `attempt_provision`
(`service.py:450`) does `if recharge.status != PENDING: return`, then makes the
provider network call, then `_apply_completed`/`_apply_reversed` and commits —
with **no row lock and no conditional claim** on the recharge/transaction. Two
consequences:

1. *Double provider-vend (money leak once live).* `attempt_provision` is reached
   only via `POST /recharge`. A client that retries the **same Idempotency-Key**
   while the first provider call is still in flight (the `202`/slow path makes
   retries likely) hits the idempotency fast-path (`service.py:213-222`), gets the
   committed PENDING recharge, and calls `provider.provision()` **again for the
   same `recharge_id`**. The ledger is safe (one reservation, idempotent status
   flip) but the provider is invoked more than once. Sasai never enforces
   provider-side dedupe on `recharge_id`; the simulator mints a fresh reference
   each call. With a live MNO this is duplicate airtime for one charge.
2. *Terminal-state overwrite (mischarge / lost refund).* `_apply_completed`
   (`service.py:376-380`) issues `UPDATE ledger_entries ... SET status=COMPLETED
   WHERE transaction_id=?` with **no `status='PENDING'` guard**. If a validly-
   signed `failed` callback (or an admin `resolve` REVERSED) commits between the
   line-450 read and the line-466 apply, the racing sync-attempt resurrects the
   REVERSED entries to COMPLETED — a `REVERSED→COMPLETED` transition that
   violates "terminal is terminal" (ledger-invariants §3) and can charge a user
   whose provider call actually failed (or, reversed order, overwrite a genuine
   completion with a refund). The 300s HMAC replay window (A4/residual) widens
   this race for callbacks.
   *Fix:* claim atomically — `UPDATE airtime_recharges SET status='PROVISIONING'
   WHERE id=? AND status='PENDING'` and proceed only if rowcount=1 (or
   `SELECT ... FOR UPDATE` + re-read), and add `WHERE status='PENDING'` to the
   finalising ledger/txn UPDATEs.

**A2 — Owner-scope BOLA on GET.** `get_recharge` (`service.py:512-525`) filters
`id == recharge_id AND tenant_id == tenant_id` but not `user_id`. The route
(`router.py:91-99`) passes `user.tenant_id`, so **any** authenticated user in a
tenant can read **any** recharge in that tenant — including another user's
`msisdn` (PII), `network`, and `amount` — if they learn the recharge_id (support
links, logs, the A4 oracle). UUIDv4 unguessability is the only control today.
*Fix:* also filter `AirtimeRecharge.user_id == user.id` for the user-facing route
(keep tenant-only scoping for any admin route). Note: `redemption.get_redemption`
(`redemption/router.py:169-177`) shares this pattern — flag to `backend` as a
parallel fix.

**A3 — Public dev callback secret, no prod onboarding path.** `scripts/seed.py:510`
hardcodes `AIRTIME_CALLBACK_SECRET = "dev-airtime-callback-secret-do-not-use-in-prod"`,
encrypts it onto the seeded merchant (`:566`), and prints it (`:572`). There is
**no admin API/UI to create a merchant or rotate its callback secret** (grep:
`MerchantProfile` is written only by the seed and read by the service). So the
*only* way an airtime merchant exists is the seed — meaning any environment that
ran the seed has a merchant whose callback secret is public knowledge. Anyone can
then forge signed `completed`/`failed` callbacks for that tenant's PENDING
recharges: force `completed` (user charged, provider never confirmed) or force
`reversed` on a recharge the provider already delivered (airtime **and** refund →
money leak). Gated today only by "seed is dev-only" + no non-local deploy exists.
*Fix (production gate):* refuse to seed a real secret outside dev; build a
merchant-onboarding path that generates a high-entropy secret shown once; require
rotation before go-live.

**A4 — Callback pre-auth work + existence oracle.** `POST /{id}/callback` has no
auth dependency; `verify_signature` is the gate. Before it runs, the service does
two DB lookups and a Fernet decrypt (`service.py:558-573`), and the router reads
the full body with `await fastapi_request.body()` (`router.py:115`) with **no size
cap and no rate limit**. An unauthenticated attacker can force that work per
request (resource-consumption DoS, API4). The lookup order also yields a
distinguishable response — `404` (no recharge) vs `422` (recharge exists, no
active merchant) vs `401` (recharge exists, signature fails) — a recharge-id
existence oracle (API2), bounded by UUIDv4 entropy. Mirrors Epic 14 M3/M2 and
the redemption callback. *Fix:* cap body size, add an IP/route rate limit, and
collapse pre-verify failures to one indistinguishable `401`.

**A5 — No key rotation.** `secret_box._fernet` derives one Fernet key from
`SECRET_KEY` via SHA-256 (`secret_box.py:21-30`). Rotating `SECRET_KEY` makes
every stored `callback_secret_encrypted` undecryptable; the airtime path maps
that to `SignatureNotConfigured` (401) at `service.py:567-571`, so all callbacks
break until secrets are re-encrypted, forcing manual admin-resolve. Same class as
Epic 14 M5. *Fix:* `MultiFernet` with a rotating key list + `SECRET_KEY` length
validation (shared remediation with Epic 14).

**A6 — Recharge insert idempotency + orphan window.** `post_transaction` catches
`IntegrityError` and returns the existing txn (`ledger/service.py:159-169`), but
the subsequent `AirtimeRecharge` INSERT (`service.py:296-308`) has no equivalent
guard: a genuinely concurrent same-key replay that slips past the fast-path can
hit `uq_airtime_recharges_idempotency_per_tenant` and surface as an unhandled
`500` instead of the original recharge. Separately, `post_transaction` commits
internally and `initiate_recharge` commits again at `:338`; a crash between the
two leaves a committed PENDING reservation with no `airtime_recharges` row
(orphaned reserved funds — reconciliation must sweep orphan PENDING txns).
*Fix:* wrap the recharge INSERT in the same `IntegrityError`→return-existing
pattern; ensure reconciliation covers reservation-without-recharge.

**A7 — `extra='ignore'` (informational).** `AirtimeRechargeRequest` (and the
callback/resolve schemas) omit `model_config`, so Pydantic v2 silently drops
unknown body fields. Privileged fields (`status`, `user_id`, `tenant_id`,
`provider_reference`, `verified`) are therefore **not** assignable — safe — but
silently rather than explicitly. Prefer `ConfigDict(extra='forbid')` so client
bugs / probing surface as 422 and intent is explicit.

### 5.2 Remediation status (2026-07-09)

| Finding | Status |
|---|---|
| Mass-assignment / BOPLA (T-2) | **Not applicable / clean by design** — the recharge body carries only non-privileged fields; server sets tenant/user/status/provider_reference. This was Epic 14's H1; airtime does not repeat it. |
| Overdraft (Pay-PRD-0220) | **Correct** — `balance-reserved < amount+fee` rejected before any ledger write, fee included, under a `SELECT FOR UPDATE` wallet lock (`service.py:228,259-264`). |
| Ledger append-only + net-zero | **Correct** — only `status` flips on existing entries; REVERSED drops both legs from `derive_balance`; COMPLETED flips both together; sum-to-zero preserved. |
| Tenant isolation | **Correct** for wallet / holding / initiate / callback (bound to recharge's own tenant secret). A2 is an *owner*-scope gap within a tenant, not cross-tenant. |
| Audit + PII masking | **Correct** — initiated/completed/reversed/resolved audited; msisdn masked (`mask_phone`) in initiation audit (NFR-0240); no PIN/secret logged (NFR-0170). |
| `live` mode safety | **Correct** — `get_provider('live')` raises rather than silently simulating real money. |
| **A1** | **Fixed (2026-07-09, S7)** — finalise paths claim the recharge via `SELECT ... FOR UPDATE` + PENDING re-check (`_lock_pending_recharge`; `attempt_provision` re-locks *after* the provider call, never across it), and the ledger/txn flip UPDATEs carry `status='PENDING'` guards (idempotent double-finalise). Regression: `test_resolve_on_terminal_recharge_rejected`, `test_callback_on_terminal_recharge_rejected`. Residual: provider-side dedupe on `recharge_id` is a live-provider concern (the adapter must send an idempotency token). |
| **A2** | **Fixed (2026-07-09, S7)** — the user-facing `GET /{id}` is now owner-scoped (`tenant_id AND user_id`). Regression: `test_get_recharge_rejects_other_user_same_tenant`. Parallel `redemption.get_redemption` gap flagged to `backend`. |
| **A7** | **Fixed (2026-07-09, S7)** — `AirtimeRechargeRequest` sets `ConfigDict(extra='forbid')`; unexpected body fields now 422 instead of being silently dropped. |
| **A3** | **Deferred — production gate.** Needs a merchant-onboarding path that mints a shown-once high-entropy secret + rotation; the seed secret is dev-only and labelled as such. Must land before any live-provider / non-local deploy. |
| **A4, A5, A6** | **Deferred — hardening.** Callback body cap + rate limit + uniform-401 (A4); `MultiFernet` rotation (A5, shared fix with Epic 14 M5); recharge-INSERT `IntegrityError`→return-existing guard + orphan-reservation sweep (A6). None affect the current simulator / local scope. |

## 6. Residual risks (accepted / to confirm)

- **Client webhook (Epic 17 S6, Sasai → client) is NOT implemented.** No webhook
  code exists in `backend/app` despite the task tracker marking it done. When
  built, it will POST to a **client-controlled URL** → SSRF surface. Requirements
  for that story: allowlist destination hosts, block private / link-local /
  metadata (169.254.169.254) ranges and redirects to them, enforce TLS 1.2+
  (NFR-0260), sign outbound with a per-client secret, and cap timeout/retries.
- **Live provider adapter deferred.** `provider_config` is designed to hold an
  endpoint URL that a future httpx adapter will fetch server-side → SSRF if
  `provider_config` ever becomes user-influenced. Keep it operator-only; apply the
  same allowlist/TLS/no-internal-IP controls when the adapter lands.
- **HMAC 300s replay window, no nonce store.** A captured valid callback is
  replayable within 300s; anti-replay relies on the terminal-status guard
  (PENDING→terminal), not on a nonce. Adequate for the single PENDING→terminal
  transition, but it widens the A1 race window. Revisit if any repeatable
  callback endpoint reuses this verifier.
- **Global platform-admin resolve spans tenants.** `POST /{id}/resolve` takes
  `tenant_id` in the body and any platform-admin can settle any tenant's recharge
  (intended reconciliation model; blast radius of one stolen admin token noted —
  same posture as redemption confirm/fail and Epic 14).

## 7. Required regression tests (hand to `automation-testing`)

- `test_airtime_get_rejects_other_users_recharge_same_tenant` — user B cannot GET
  user A's recharge in the same tenant (A2).
- `test_airtime_concurrent_finalize_single_vend_and_no_terminal_overwrite` —
  concurrent attempt-provision + callback/resolve results in exactly one provider
  vend and never flips a REVERSED recharge back to COMPLETED (A1).
- `test_airtime_callback_replay_after_settled_returns_409` — replaying a valid
  callback after settlement is a no-op 409.
- `test_airtime_callback_failures_indistinguishable` — unknown id, no-merchant,
  and valid-id-bad-signature all return the same `401` error_code (A4).
- `test_airtime_recharge_rejects_or_ignores_privileged_body_fields` — sending
  `status`/`user_id`/`tenant_id`/`provider_reference`/`verified` does not affect
  the created recharge (T-2 / A7).
- `test_airtime_overdraft_rejects_amount_plus_fee_before_write` — no ledger rows
  are written when `available < amount + fee`.
- `test_airtime_reversal_nets_to_zero_and_restores_available` — REVERSED refund
  restores the wallet including fee legs; ledger sum-to-zero holds.
- `test_airtime_callback_cross_tenant_secret_rejected` — a tenant-A recharge
  cannot be settled with a tenant-B merchant secret.
- `test_airtime_ledger_append_only_no_money_update` — finalisation issues no
  UPDATE against ledger money columns (status only).
- `test_airtime_idempotent_replay_no_second_reservation` — same key returns the
  original recharge with no second ledger transaction (and no unhandled 500, A6).
- `test_secret_box_rotation_with_multifernet` — a secret encrypted under key v1
  still decrypts after v2 is prepended (A5; shared with Epic 14).

## 8. Sign-off

- [x] STRIDE pass complete
- [x] OWASP API Top 10 (2023) pass complete
- [x] Fintech-specific scenarios (tenant isolation, idempotency/double-spend,
  callback replay, enumeration, secret disclosure, overdraft, ledger append-only)
  exercised against code
- [x] No HIGH findings in the current simulator-only / local-only scope; no
  cross-tenant breach and no ledger-level double-spend found
- [x] A1 (concurrency claim) resolved (2026-07-09, S7) — row-lock claim
  (`_lock_pending_recharge`) + PENDING-guarded finalise UPDATEs. Residual:
  provider-side dedupe on `recharge_id` is a live-provider gate.
- [x] A2 owner-scope filter added (2026-07-09, S7).
- [x] A7 `extra='forbid'` on the recharge schema (2026-07-09, S7).
- [ ] A3 (dev-secret / merchant onboarding) — **mandatory before any
  live-provider or non-local deployment**
- [ ] A4–A6 hardening — follow-up (A5 shares Epic 14's MultiFernet fix)
- Reviewed by: security agent (adversarial) on 2026-07-09; fixes applied by lead 2026-07-09
