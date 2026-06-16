# Architectural Decisions — Sasai Wallet & Rewards Platform

A flat log of architectural decisions made during genesis-init and subsequent sessions. Append-only — never edit past entries; instead, write a new entry that supersedes.

---

## 2026-05-28 — Genesis init

### Scale tier
**Decision:** Tier 3 — Enterprise.
**Why:** Multi-tenant, 99.5% uptime, 7-year retention, ledger-style design, audit trail everywhere, Keycloak SSO, Kafka backbone. Single-tenant or simpler stacks would not satisfy NFR-0090, NFR-0150, NFR-0220.

### Stack lock-in (from Technical PRD v1.0)
- Backend: Python 3.12 + FastAPI 0.136.3 + SQLAlchemy 2.0.50 + Alembic 1.18.4 + Pydantic v2
- Database: PostgreSQL (local for now, managed in prod)
- Bus: Apache Kafka via confluent-kafka, partition key = `user_id`
- Auth: Keycloak (admin/operator only) + custom PIN/OTP for end users
- Queue: Celery + Redis
- Admin UI: Next.js 16.2.6 + TypeScript + App Router + shadcn/ui + Tailwind
- Node: 22.22.2, npm 10.9.7

### Mobile deferred to Phase 2
**Decision:** No mobile app (Expo) in Phase 1.
**Why:** User explicitly scoped to admin UI only on 2026-05-28. The Technical PRD originally included `mobile/` but we omit it.
**How to apply:** Do not scaffold `mobile/`. The `<mobile>` agent and `frontend-mobile.md` rule file are also omitted.

### AI/ML deferred to Phase 2
**Decision:** Phase 1 is strictly rule-based.
**Why:** PRD already defines a rich rules engine with 7 rule types covering loyalty patterns. LLM nudges, behavioural segment auto-suggestion, and fraud anomaly scoring are explicitly deferred.

### Ledger invariants (non-negotiable)
- **Append-only.** Every state change is a new `ledger_entries` row. Never UPDATE.
- **Reversal = new entry**, never deletion or modification of the original.
- **Balance is derived**, not stored authoritatively. `account_balance_snapshots` is a read-optimisation snapshot, never a source of truth for writes.
- **Double-entry.** Every transaction produces at least one DEBIT and one CREDIT; system-wide sum is always zero (NFR-0100).
- **External calls outside DB transactions** (Pay-PRD-0270, NFR-0130).

### Multi-tenancy pattern
**Decision:** Tenant isolation enforced at application layer via `tenant_id` column on every domain table; resolve from auth token on every request.
**Why:** Simpler than PostgreSQL RLS for Phase 1; acceptable given platform-admin role audit trails and single-codebase deployment. Revisit RLS if compliance audit demands defense-in-depth at DB layer.

### Idempotency
**Decision:** Every state-mutating endpoint requires an `Idempotency-Key` header. Backend stores in `transactions.idempotency_key` (unique per tenant). Duplicate keys return the original response (Pay-PRD-0200).

### Kafka topic conventions
- Topics defined in `app/config.py` as constants
- Partition key = `user_id` always (preserves per-user order)
- Producers emit AFTER DB commit
- Consumers idempotent — check `event_ingestion_log` before processing

### Auth split
**Decision:** Keycloak for admin/operator UI only (realm: `wallet-platform`, clients: `admin-ui`, `backend-service`). User-facing PIN/OTP is custom in `app/modules/identity/`.
**Why:** PRD specifies PIN/OTP for USSD users and mobile app users; Keycloak adds friction for these channels.

### Agent roster
9 agents: lead, backend, data, rules-engine, admin-ui, platform, infra, compliance.
**Why rules-engine is separate:** Module 9 has 7 rule types with non-trivial progress tracking, streak windowing, composite condition evaluation. Pulling it out of `backend` ensures focused review.

### Documents location
`/Users/manan/Downloads/wallet-platform-prd-v1_0.md` and `wallet-platform-technical-prd-v1_0.md` are the source PRDs. `docs/02-prd.md` and `docs/05-technical-architecture.md` are local distillations + pointers. Update both if PRD evolves.

### Working directory
Flat scaffold at `/Users/manan/Documents/Sasai_Wallet/`. No sub-project folder. Top-level dirs: `backend/`, `admin-ui/`, `sasai-wallet-infra/`, `scripts/`, `docs/`, `.claude/`.

### Infra in Docker only (2026-06-16)
Renamed `infra/` → `sasai-wallet-infra/`. Added Postgres to the Compose stack — no standalone Postgres on the host any more. Containers are named with the project prefix (e.g. `sasai-wallet-infra-kafka-1`). The Kafka topics script's `KAFKA_CONTAINER` default updated accordingly.

---

## 2026-05-28 — Coding standards + review/testing agents added

### Master coding guidelines established
**Decision:** Adopt explicit coding standards at `.claude/rules/coding-guidelines.md` with `paths: ["**/*"]` so they're loaded for every file edit.

The four user-stated principles:
1. **Simple code, no duplicates, easy to maintain.** Grep before writing new helpers. DRY threshold: 2 occurrences = consider util, 3 = must be util.
2. **Comments required.** Every file gets a top-of-file docstring; every function/class gets a docstring with purpose, args, returns, raises, side effects. This OVERRIDES the default "minimal comments" stance.
3. **Backend automation tests required** for every exposed interface — API endpoints AND Kafka producers/consumers. 80% line coverage on `backend/app/`.
4. **Frontend automation tests deferred.** Do NOT write Vitest/Playwright for `admin-ui/` unless user explicitly asks.

**Why:** User explicit instruction. The defaults of "no comments unless WHY is non-obvious" and "small focused tests" don't match their preference — they want documentation density and full interface coverage.

**How to apply:** Always read `.claude/rules/coding-guidelines.md` before any code edit. Every new function gets a docstring even if the name seems self-explanatory.

### Two new agents added: `code-review` and `automation-testing`
**Decision:** Add these two agents to fill enforcement gaps the original 8-agent roster missed.

- **`code-review`** runs automatically before every commit of feature work, on any multi-file change (>3 files), on any change touching sensitive surfaces (ledger / payments / redemption / auth / external APIs), or on user request. Output is a structured PASS/FAIL/N/A checklist across coding guidelines, architecture, ledger invariants, multi-tenancy, security, test coverage, PRD traceability, and performance NFRs.

- **`automation-testing`** owns ALL backend tests — endpoints, Kafka producers, Kafka consumers, ledger invariants, tenant isolation. Runs after every new endpoint / consumer / producer / model / rule type, when `code-review` flags missing coverage, or on user request. Explicitly does NOT write frontend tests in Phase 1.

**Why:** Solo founder needs structural enforcement of the user's guidelines without relying on memory or discipline alone. These two agents make the gates automatic.

**How to apply:** The `lead` agent invokes them at the trigger points above. They do not write production code; `code-review` audits, `automation-testing` writes tests against existing production code.

### Test infrastructure conventions
- Real PostgreSQL test DB (not SQLite) — schema parity matters
- Captured-message fixture for Kafka unit tests; optional testcontainers integration tests
- `freezegun` for time-sensitive tests; never shim datetime
- Never mock the application's own service functions — test through the endpoint
- Invariant tests in `tests/invariants/` run at end of every session

### Security / VAPT specialist agent added
**Decision:** Add `security` agent — adversarial specialist owning threat modeling, OWASP API Top 10 testing, fintech-specific exploit scenarios (15 documented), crypto review, and dependency CVE scanning.

**Why three separate security-related agents:** Each has a distinct stance.
- `compliance` is defensive policy: does the design meet PII / retention / audit / regulatory rules?
- `code-review` is a defensive gate: does the diff comply with our internal rules?
- `security` is offensive: how would an attacker break this?

This three-layer model is intentional for a fintech. Compliance says "the rules say X"; code-review says "this diff follows X"; security says "an attacker can still extract money despite X — here is the proof".

**How to apply:** `lead` agent invokes `security` at TWO points in the workflow:
1. **Before coding** for any new module touching auth/money/PII — STRIDE threat model informs design.
2. **After coding** for the same surfaces — active VAPT on the completed diff before commit.

Critical/High findings block commit; Medium/Low go to follow-up. Quarterly full sweep is calendar-driven.

**Artifacts owned:** `docs/security/threat-models/`, `docs/security/vapt-reports/`, `docs/security/playbook.md`. Regression tests handed to `automation-testing` for permanent coverage.

### Agent roster — final (11 agents)
lead, backend, data, rules-engine, admin-ui, platform, infra, compliance, code-review, automation-testing, security.

---

## 2026-05-28 — Phase A shipped (Identity + Accounts + Ledger foundation)

### What landed
- Models: User, UserIdentifier, UserProfile, OtpRequest (scaffold), AuthAttempt (scaffold), Account, AccountBalanceSnapshot, Transaction, LedgerEntry
- Migration `0002` — 9 new tables, applied successfully
- Endpoints (TEST-ONLY, no auth):
  - `POST /api/v1/identity/users` — register user
  - `GET /api/v1/identity/resolve/{type}/{value}?tenant_id=...` — identifier → user_id
  - `POST /api/v1/accounts` — create account (all 4 types)
  - `GET /api/v1/accounts/{id}/balance?tenant_id=...` — derived balance
- Ledger service `post_transaction()` — atomic double-entry with idempotency, sum-to-zero, account-exists checks
- 27 tests passing, **81% coverage** (above the 80% threshold)
- Seed script populates Sasai-ZA tenant + Alice + Bob + system_points_issuance + provider_redemption_wallet

### Schema clarification — `system_points_issuance` account type
**Decision:** Added a 4th `accounts.account_type` value (`system_points_issuance`) — the master debit source for reward issuance. Without it, the PRD's "credit points to user" requirement (Pay-PRD-0620) has no offsetting debit and breaks the sum-to-zero invariant (NFR-0100).

**Why:** Every CREDIT must have a DEBIT. The PRD assumed but never named this account. Documented in `docs/06-data-architecture.md` §4 addendum.

**How to apply:** Each tenant has exactly one `system_points_issuance` account (auto-created in seed). Reward issuance posts DEBIT system → CREDIT user_points. Its balance trends negative; the negative number equals total points outstanding across all user/provider accounts.

### Phase A accepted residual risks (all to be resolved in Phase 2)
- **No auth on test endpoints** — endpoints accept `tenant_id` in body/query and are tagged `test-only` in OpenAPI. Phase 2 wires Keycloak.
- **Identifier value in URL path** for resolve endpoint — soft PII concern in proxy logs. Move to query/body or header in Phase 2.
- **No audit log writes** for user/account creation — re-introduced in Phase 2 alongside auth.
- **`masking.py` helpers written but unused** in Phase A code paths. They exercise in Phase 2 when logging is wired.

### Test infrastructure decisions
- Test DB: separate `wallet_platform_test` database, schema created via `Base.metadata.create_all` at session start (not Alembic — `alembic check` enforces parity)
- Per-test isolation: TRUNCATE all domain tables before each test (NOT SAVEPOINT rollback — asyncpg + SAVEPOINT had connection-state issues)
- Test engine uses `NullPool` so every operation gets a fresh asyncpg connection — eliminates "another operation in progress" errors
- Fixtures COMMIT after seeding so endpoint-spawned sessions see the data

### Next phases (in order)
- **Phase B — P2P**: Payments module with P2P transfer using the ledger; limits + pricing stubs. **[shipped 2026-05-28 — see entry below]**
- **Phase C — Rewards inflow**: Kafka consumer for `wallet.events.external` → simplified rules engine → reward issuance (DEBIT system_points_issuance → CREDIT user_points).
- **Phase D — Redemption**: Redemption module + catalog endpoints (lifetime earned, redeemed, available).
- **Phase E — Admin UI shell**: Next.js + Keycloak login + Users / Transactions pages so the system is visible.

---

## 2026-05-28 — Phase B shipped (P2P transfers)

### What landed
- **`POST /api/v1/payments/p2p`** — atomic P2P with `Idempotency-Key` header, overdraft prevention (Pay-PRD-0220), recipient resolved by identifier (Pay-PRD-0250 + Pay-PRD-0060), self-transfer guard, currency match check.
- **Internal `top_up()` service** — debit `system_cash_inflow` → credit user's financial_wallet. Used by seed; HTTP endpoint deferred (Pay-PRD-0320).
- **`SELECT FOR UPDATE` on sender wallet** — serialises concurrent transfers from the same wallet; the concurrent double-spend test proves only one wins.
- **Migration `0003`** — added `system_cash_inflow` to `accounts.account_type` CHECK constraint.
- **Phase B threat model** at `docs/security/threat-models/phase-b-p2p.md`.
- **Seed updated** — Alice opens with R 1000, Bob with R 500 (idempotent via per-user keys).
- **37 tests passing**, 81% line coverage.

### Live demo (Alice → Bob R 250) verified
- Before: Alice R 1000, Bob R 500
- After: Alice R 750, Bob R 750
- Idempotent replay: same txn_id, balance unchanged
- Overspend attempt: 409 insufficient_funds
- `ledger_sum_to_zero` invariant: holds (drift = 0.000000)

### Schema clarification — `system_cash_inflow`
**Decision:** Added a 5th `accounts.account_type` value (`system_cash_inflow`) — debit-side master for money entering from outside (top-ups, external receipts).

**Why:** Same reason as Phase A's `system_points_issuance` — every CREDIT to a user wallet needs an offsetting DEBIT. The PRD's top-up requirement (Pay-PRD-0320) implies but doesn't name this account. Documented in `docs/06-data-architecture.md` §4 second addendum.

**How to apply:** One `system_cash_inflow` per (tenant, currency). Auto-created on first top-up by `_get_or_create_system_cash_inflow()`. Its balance trends negative; the negative number equals total user-held cash in that currency.

### PRD orchestration sequence — partially implemented
PRD Pay-PRD-0260 mandates: (1) role check → (2) limits check → (3) pricing → (4) ledger write. Phase B implements step (4) only; steps (1)–(3) are explicit TODOs in `payments/service.py` with PRD refs. Architecture supports plugging them in later without changing callers.

### Concurrency invariant proven
`test_p2p_concurrent_double_spend_blocked` — two simultaneous full-balance transfers. Only one succeeds; the other gets 409. The PostgreSQL row-level lock on the sender wallet is what makes this work.

### Phase B residual risks (carried to Phase 2 auth wiring)
- No auth — `sender_user_id` in body, endpoint flagged `test-only`
- No limits / pricing / role check
- No rate limiting
- No audit log writes

---

## 2026-05-29 — Phase C shipped (Kafka → rewards inflow)

### What landed
- **Models**: Rule + RuleCondition + UserRuleProgress + RewardEvent + ExternalEventSource + EventIngestionLog (PRD §6.8, §6.9, §6.11).
- **Migration `0004`** — 6 new tables, applied cleanly.
- **Events module** — source registration (`POST /events/sources`), event ingestion (`POST /events/external`), normaliser stub.
- **Rules module** — rule CRUD (`POST /rules`, `GET /rules`), evaluator with `first_time` + `milestone` (Pay-PRD-0617, Pay-PRD-0540, Pay-PRD-0570).
- **Rewards module** — `issue_points_reward()` writes a balanced ledger transaction (DEBIT system_points_issuance → CREDIT user.points_account).
- **Kafka consumer** at `scripts/run_consumer.py` — subscribes to `wallet.events.external`, calls the same `process_external_event` service.
- **Kafka publisher** at `scripts/publish_event.py` — helper for manual end-to-end testing.
- **Seed updated** — registers sample source `sasai-bank` + two sample rules ("First top-up bonus" = 100 pts, "3 P2P milestone" = 50 pts).
- **56 tests passing**, 82% line coverage.
- **Phase C threat model** at `docs/security/threat-models/phase-c-rewards-inflow.md`.

### Live demo (Kafka → rewards) verified
Published 5 events via `publish_event.py`:
- Alice's first `top_up` → first_time rule fires → **+100 pts**
- Alice's second `top_up` → first_time skipped (already fired)
- Alice's 1st, 2nd, 3rd `p2p` → milestone fires on the 3rd → **+50 pts**

Result: Alice points 0 → 150. `system_points_issuance` balance = -150. Ledger drift = 0.000000.

### Idempotency layers (defence in depth)
1. **`event_ingestion_log` UNIQUE(source_key, external_event_id)** — replay = no-op
2. **`reward_events` UNIQUE(user_id, rule_id, triggering_event_id)** — even if event is re-evaluated, reward issuance is idempotent
3. **`transactions.idempotency_key` deterministic** — `reward:{rule_id}:{user_id}:{triggering_event_id}` ensures the ledger writes are idempotent

### Phase C scope decisions
- Rule types: first_time + milestone only. Full 7-type schema in place — other types are code-only additions.
- Normaliser: identity mapping. `field_mapping JSONB` exists but unused until partner schemas land.
- HMAC verification: `shared_secret` column scaffolded but NOT enforced (Phase F).
- No segment binding, bonus multipliers, cashback rewards in Phase C.

### Phase C residual risks (Phase F)
- No auth on rule/source CRUD or event ingestion
- HMAC verification not enforced even when secret is set
- Caller can register a high-value rule and trigger via Kafka
- Acceptable for local dev only — endpoints tagged `test-only` in OpenAPI

---

## 2026-05-29 — Phase D shipped (Redemption + catalog)

### What landed
- **Models**: `RedemptionProvider` + `Redemption` (PRD §6.10) with a non-PRD-literal addition: `redemption_providers.redemption_wallet_account_id` FK to the auto-created provider wallet.
- **Migration `0005`** — 2 tables + 3 indexes, applied cleanly.
- **Redemption module**:
  - `POST /api/v1/redemption/providers` — auto-creates the provider's `provider_redemption_wallet` account
  - `POST /api/v1/redemption/initiate` — overdraft-checked, two-legged PENDING ledger write (Pay-PRD-0670, Pay-PRD-0740)
  - `POST /api/v1/redemption/{id}/confirm` — flips entries PENDING → COMPLETED (Pay-PRD-0690)
  - `POST /api/v1/redemption/{id}/fail` — flips entries PENDING → REVERSED, restores points (Pay-PRD-0700)
  - `GET /api/v1/redemption/{id}` — status lookup
- **Catalog module**:
  - `GET /api/v1/catalog/{user_id}/summary` — available + lifetime_earned + lifetime_redeemed (Pay-PRD-0970)
  - `GET /api/v1/catalog/{user_id}/redemption-history` (Pay-PRD-1030)
- **Seed updated** — registers "Mukuru Voucher (sample)" redemption provider on first run.
- **72 tests passing** (16 new for Phase D).
- **Phase D threat model** at `docs/security/threat-models/phase-d-redemption.md`.

### Live demo verified
- Alice starts at 150 pts available (from Phase C).
- Initiate 60 → status PENDING, available=90, reserved=60.
- Overdraft attempt for 200 → 409 insufficient_funds.
- Confirm → status COMPLETED, lifetime_redeemed=60, available stays at 90.
- Initiate 30 then fail → status FAILED, available stays at 90 (the 30 is released).
- Ledger drift: 0.000000.

### Overdraft prevention via row-level lock
Same pattern as Phase B P2P: `_lock_account_for_update(user_points)` then `derive_balance` under lock, reject if `available < amount` before any ledger write. The `test_initiate_concurrent_double_spend_blocked` test proves it.

### Append-only with status flip
PENDING → COMPLETED / REVERSED is the ONE allowed mutation on ledger entries (see `ledger-invariants.md`). No new compensating entries are needed for redemption fail because PENDING entries were never in `derive_balance` (they only counted as `reserved`). Flipping to REVERSED removes them cleanly.

### Schema clarification — `redemption_wallet_account_id`
The PRD's literal §6.10 schema doesn't link providers to their wallet. Added the FK explicitly so redemption code never has to "guess" which account to credit. One wallet per provider per tenant, auto-created on registration.

### Phase D residual risks (Phase F + later)
- No auth on initiate/confirm/fail
- Confirm/fail are TEST-ONLY simulators of the provider — production needs HMAC-verified provider callback handlers (Phase F)
- No reconciliation sweep — PENDING redemptions persist until manually resolved (Phase E)
- No notifications (Pay-PRD-0640 deferred)

### What completes the platform loop
With Phase D, the round trip works end-to-end:
**External event → rule fires → points credited → user redeems → provider confirms → user receives cash value.**
All steps idempotent, ledger always balanced, full audit trail.

### Phase D closeout (2026-05-29, later)
Added the last leftovers to fully close Phase D:
- `GET /api/v1/catalog/{user_id}/points-history` (Pay-PRD-0980) — granular ledger view per points entry with `rule_name` + `triggering_event_id` for reward credits, transaction_type for redemptions
- Tests: cross-tenant fail (mirror of cross-tenant confirm), confirm-then-fail rejects (mirror of confirm-then-confirm), 4 points-history scenarios
- **78 tests passing** (up from 72)
- Live demo: Alice's points history surfaces 2 rewards (rule name + event id) + 1 COMPLETED redemption + 1 REVERSED redemption — full audit trail in one call
