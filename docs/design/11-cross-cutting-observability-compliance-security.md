# 11 — Cross-cutting: Observability, Compliance & Security

> **Document type:** Design (HOW). The concerns that touch every module — structured logging, PII masking,
> the immutable audit trail, retention, tenant isolation, encryption, auth/session security, the analytics
> module, and the security/compliance posture.
> **Related:** [`.claude/rules/observability.md`](../../.claude/rules/observability.md),
> [`.claude/rules/compliance-fintech.md`](../../.claude/rules/compliance-fintech.md) (the source rules — this
> doc explains how they are *implemented*, it does not restate them),
> [`docs/security/threat-models/`](../security/threat-models/) (STRIDE threat models).
> **README:** see the [design index](README.md) §8. Maps to **NFR-0090..0280**.
> **Audience:** an engineer touching any surface that logs, audits, authenticates, or reports.

---

## 1. Structured logging (NFR-0170)

Backend logging is **`structlog`** with JSON output in production. The conventions
([`observability.md`](../../.claude/rules/observability.md)):

- **No `print()`, no f-string interpolation of data.** Context goes through structured fields, bound once at
  request entry: `log.bind(request_id=…, user_id=…, tenant_id=…, trace_id=…)`.
- **Never logged in any form:** PINs, OTPs, session tokens, full card numbers, full account numbers. Amounts
  are *not* PII — log the full amount with its currency.
- **Every error log** carries `request_id`, `user_id` (never a raw identifier), `tenant_id`, `error_code`
  (matching the API `error_code`), `error_message`, and a server-side-only `stack_trace` (never in the API
  response — all app exceptions subclass `AppHTTPException` and serialise to a lean `{error_code, message}`).
- **Frontend:** admin server actions emit a structured `{action, user_id, tenant_id, success}` line; the
  browser console is used sparingly; Sentry routing is Phase 2. The mobile API client
  ([`mobile/lib/api/client.ts`](../../mobile/lib/api/client.ts)) never logs the response body or the
  `Authorization` header.

Metrics (Prometheus `/metrics`) and OpenTelemetry traces are wired-for but Phase 2 — the `trace_id` slot is
already reserved in the structlog context.

## 2. PII masking (NFR-0240)

Identifiers must be masked before they reach any application log. The **only** sanctioned helpers live in
[`backend/app/shared/utils/masking.py`](../../backend/app/shared/utils/masking.py) — improvising a mask is a
review failure.

| Helper | Example |
|---|---|
| `mask_phone` | `+27 82 555 0142` → `+2782 *** 0142` (first 4 + last 4 digits) |
| `mask_email` | `jane@example.com` → `j***@example.com` |
| `mask_account` | `ZA-001-887-2210` → `ZA-0***2210` |
| `mask_card` | `5234 5678 9012 3456` → `5234 **** **** 3456` (PCI first-4/last-4) |
| `mask_identifier(type, value)` | dispatches to the right helper by identifier type |

All four return a safe `***`/`****` sentinel for values too short to mask meaningfully. **Credential storage**
(from `compliance-fintech.md`): PIN + OTP are bcrypt hashes (`passlib`); session tokens live in Redis only,
never the DB; full card numbers are never stored (tokenised reference only); full account numbers are stored
but masked in logs.

## 3. The immutable audit log (NFR-0160, NFR-0250)

`audit_log` is the compliance system of record — distinct from the ephemeral application log, which may be
sampled and must never be relied on for compliance evidence. Every write goes through one central writer,
[`backend/app/modules/audit/service.py`](../../backend/app/modules/audit/service.py) `record_audit(...)`,
which **adds the row to the session but does not commit** — the caller commits it *alongside* the domain-state
change so the audit row lands or disappears **atomically** with the action it records.

Each row captures: `actor_id` (user UUID / Keycloak `sub` / `"system"` / prefixed `provider:<id>` /
`source:<key>`), `actor_type` (`user`|`admin`|`system`), `action` (`<entity>.<verb>` convention, e.g.
`redemption.confirmed.by_provider`), `entity_type`, `entity_id`, `before_state` + `after_state` JSONB,
`ip_address` (from `request.client.host`), and `created_at`. The table has **no `updated_at`** — entries are
immutable and no automated process may delete from it.

**What writes to it:** every admin/config/money state transition — all three maker-checker subsystems
(config/money/user operations write a review row + an audit row per action), treasury movements, identity
admin actions, redemption + airtime provider settlements, and state transitions on `transactions`,
`redemptions`, and `user_rule_progress`. Admin display names are resolved for human-readable rows via
[`modules/admin_profiles/`](../../backend/app/modules/admin_profiles/) (`record_audit_for_admin` upserts the
Keycloak display name so audit rows read as names, not UUIDs). The admin UI surfaces the log read-only at
`/audit` and via reconciliation's `GET /api/v1/reconciliation/audit`.

> **Known gap (Epic 14).** The partner-facing external user-creation path does not yet write an audit row on
> create. Tracked as an Epic-14 audit gap — see the [external-API threat model](../security/threat-models/epic-14-external-api.md).

## 4. Retention (NFR-0150)

| Table | Minimum retention | Enforcement |
|---|---|---|
| `ledger_entries`, `transactions` | 7 years | **No purge job** — these tables grow. |
| `audit_log` | 7 years | No purge job. |
| `security` events (auth attempts) | 7 years | No purge job. |
| `otp_requests` | 30 days | Celery-beat purge. |
| `event_ingestion_log` | 90 days | Celery-beat purge. |

The three 7-year tables are deliberately purge-free; only the short-lived OTP and event-dedup tables have
background purge jobs.

## 5. Tenant isolation (NFR-0220)

`tenant_id` is on **every domain table** and is always resolved from the auth principal (the Keycloak JWT for
admins, the Redis session for users, the API key for partners) — **never** from the request body. Every query
against a domain table filters by that `tenant_id`, so a cross-tenant read returns 404/403, not another
tenant's data. This is an invariant, not a convention: **a failing tenant-isolation test is a PR blocker**,
and `python-backend.md` requires an isolation test for every domain endpoint. See invariant #7 in
[CLAUDE.md](../../CLAUDE.md) and the per-endpoint test requirement in
[`.claude/rules/testing.md`](../../.claude/rules/testing.md).

## 6. Encryption & proof-of-origin (NFR-0260, Pay-PRD-0495)

- **In transit:** all external calls (payment rails, redemption providers, event sources) go over **TLS 1.2+**
  — no "internal trust" exceptions.
- **At rest:** shared secrets (event-source and redemption-provider `shared_secret`) are sealed with **Fernet**
  via [`backend/app/auth/secret_box.py`](../../backend/app/auth/secret_box.py) rather than stored in plaintext.
- **Proof-of-origin (HMAC):** every external event source and every provider **callback** (airtime,
  redemption) is authenticated by an HMAC `X-Sasai-Signature` header verified in-service by
  [`backend/app/auth/hmac.py`](../../backend/app/auth/hmac.py). A source must be registered first; a failure
  (missing / malformed / timestamp-skewed / invalid / not-configured signature — the `signature_*` exception
  family, all 401) is **rejected and audit-logged** with source identifier + timestamp + reason.

## 7. Auth & session security (NFR-0180, NFR-0190, NFR-0280)

Two independent auth realms, both backed by [`backend/app/auth/`](../../backend/app/auth/):

- **Admin** — Keycloak JWT (RS256, verified against **JWKS** in `keycloak.py`) → `AdminPrincipal`, gated by
  `require_admin_role(...)`. The admin UI's next-auth session ([09-admin-ui](09-admin-ui.md) §2) is a
  convenience layer; the **backend re-validates every JWT** — the front-end never holds the authority.
- **User** — custom PIN/OTP with **Redis-backed sessions** (`sessions.py`, sliding TTL) → `UserPrincipal`.
  Session inactivity timeout ≤ 5 min (USSD) / ≤ 15 min (mobile); a new session on the same channel invalidates
  the earlier one. Failed PIN/OTP attempts trigger a configurable **lockout** (`lockout.py`); rate limiting is
  `rate_limit.py` → `RateLimited` (429).
- **Step-up** — `enforce_step_up` is **fail-closed**: a transaction over the configured threshold with no PIN
  → `StepUpRequired` (401); a wrong PIN → `InvalidStepUpPin` (401). This is what the mobile uniform step-up
  pattern ([10-mobile](10-mobile-app.md) §6) rides on.
- **Partner** — API keys via `require_api_key`; secrets are shown once at mint and revocable.

**PII / credentials never appear** in tokens' log lines, audit rows, or error envelopes (§1–2).

## 8. Analytics & reporting

[`backend/app/modules/analytics/`](../../backend/app/modules/analytics/) is a **read-only** per-currency KPI
module (auth = `_require_finance_or_admin`, i.e. a finance OR platform-admin realm role). Its two load-bearing
disciplines:

- **Money is NEVER summed across currencies.** Every money metric is reported per currency; the dashboard
  ([09-admin-ui](09-admin-ui.md) §4) renders one line/card per currency and refuses to add them. Non-money
  KPIs (user counts, DAU/WAU/MAU) aggregate normally.
- **Revenue = operator fee only** — commission and tax pass-throughs are not revenue.

Endpoints (all GET under `/api/v1/analytics`): `/currencies`, `/summary`, `/transactions/{timeseries,
by-service, by-status}`, `/users/{timeseries, active, by-type}`, `/revenue/by-service`, `/rewards/timeseries`,
`/liquidity`, `/net-flow`. Invalid params → `InvalidAnalyticsParameter` (422). Being read-only over the
append-only ledger, it never mutates state.

## 9. Security posture & compliance deferrals

Adversarial security work is tracked as **STRIDE threat models** under
[`docs/security/threat-models/`](../security/threat-models/) — one per sensitive surface
(`phase-a-foundation`, `phase-b-p2p`, `epic-14-external-api`, `epic-17-airtime`, `epic-18-external-treasury`,
plus the `_template`). New auth/money/PII surfaces get a model before ship (see the `security` agent triggers
in [CLAUDE.md](../../CLAUDE.md)).

**Phase-1 deferrals** (documented in `compliance-fintech.md` — on the roadmap, *not* built; do not assume they
exist):

| Deferred | Phase-1 substitute |
|---|---|
| KYC / AML transaction monitoring | limits + thresholds only ([03-money-controls](03-money-controls-pricing-limits-roles-step-up.md)) |
| PCI scope | no card data stored — tokenised reference only |
| SOC 2 / ISO 27001 controls | — |
| Sanctions screening | — |
| Fraud auto-block (NFR-0270) | **flag-only** — >24h reward-issuance-volume threshold flags for admin review, never auto-blocks in Phase 1 |

When any deferral is requested, `compliance-fintech.md` is the file that flips it from "Phase-1 deferred" to
"Phase-2 active".
