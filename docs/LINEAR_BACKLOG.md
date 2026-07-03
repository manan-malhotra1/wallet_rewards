# Linear Backlog — Sasai Wallet & Rewards Platform

> **Purpose:** Importable backlog for Linear, organised as Epics × Stories.
> Each story has acceptance criteria, PRD references, and current status.
>
> **Source PRDs:**
> - Product: `docs/02-prd.md` (linked to v1.3)
> - Technical: `docs/05-technical-architecture.md`
> - Data: `docs/06-data-architecture.md`
> - UI: `docs/04-ui-layouts.md`

**Status legend:** `Done` · `In Progress` · `Backlog` · `Deferred`

---

## Epic 1 — Foundation (Identity + Accounts + Ledger) · **Done**

Phase A. The substrate every other capability stands on. Ledger is the source
of truth for all balances; identity resolves any registered identifier
(phone/email/account/card) to a canonical user_id; accounts hold money or
points per user per tenant.

### Story 1.1 — User registration with multi-identifier support · Done

**Description:** Implement Module 1 (Identity). Users register with one or
more identifiers; identifier values are tenant-scoped unique; profile data
optional.

**Acceptance criteria:**
- `POST /api/v1/identity/users` returns 201 with `{id, tenant_id, status, identifiers}`
- Duplicate identifier in same tenant → 409 `identifier_already_in_use`
- Same identifier value across different tenants → both allowed
- Unknown tenant_id → 404 `tenant_not_found`
- Validation: at least one identifier required; identifier_type must be one of phone/email/account_number/card_number

**PRD:** Pay-PRD-0010, 0050, 0070

### Story 1.2 — Identifier resolution endpoint · Done

**Description:** Any registered identifier resolves to canonical user_id within a tenant.

**Acceptance criteria:**
- `GET /api/v1/identity/resolve/{type}/{value}?tenant_id=...` returns `{user_id, tenant_id, identifier_type}`
- Unknown identifier → 404 `user_not_found`
- Cross-tenant identifier lookup returns 404 (no existence leak — NFR-0220)

**PRD:** Pay-PRD-0060 · **NFR:** 0220

### Story 1.3 — Account model with 5 types · Done

**Description:** Account model supports financial_wallet, points_account, system_points_issuance, provider_redemption_wallet, system_cash_inflow.

**Acceptance criteria:**
- `POST /api/v1/accounts` creates an account
- `GET /api/v1/accounts/{id}/balance?tenant_id=...` returns derived balance
- Cross-tenant balance read → 404
- Currency normalised to uppercase on write
- Invalid account_type → 422

**PRD:** Pay-PRD-0110, 0120, 0130, 0140 · **Addendum:** docs/06-data-architecture.md §4

### Story 1.4 — Internal ledger service with double-entry invariants · Done

**Description:** All ledger writes go through one service. Every transaction is at least 2 entries that balance to zero. Idempotency keyed per tenant.

**Acceptance criteria:**
- Atomic two-leg posting via `post_transaction(...)`
- Reject if entries don't sum to zero (422 `unbalanced_transaction`)
- Reject single-entry transactions
- Idempotency: same (tenant_id, idempotency_key) → existing transaction returned
- Reject when any referenced account isn't in the tenant
- All-zero amounts rejected

**PRD:** Pay-PRD-0170, 0180, 0200 · **NFR:** 0100

### Story 1.5 — Append-only ledger structural guarantee · Done

**Description:** `ledger_entries` table has no `updated_at` column; code never issues UPDATE against it.

**Acceptance criteria:**
- Migration creates table without `updated_at`
- Invariant test asserts the column doesn't exist
- System-wide invariant test: `SUM(CREDIT) - SUM(DEBIT) = 0` across all COMPLETED entries

**PRD:** Pay-PRD-0170 · **NFR:** 0100

### Story 1.6 — Seed script + 2 test users + system_points_issuance · Done

**Description:** Idempotent seed that primes the database for local testing.

**Acceptance criteria:**
- Creates Sasai-ZA tenant (wallet mode, ZAR)
- Creates Alice (+27 82 555 0001) and Bob (+27 82 555 0002) with phone identifiers
- Each user gets one financial_wallet (ZAR) + one points_account (PTS)
- Creates one system_points_issuance master account per tenant
- Re-running the script is a no-op (no duplicates)

**PRD:** Schema addendum docs/06-data-architecture.md §4

---

## Epic 2 — P2P Transfer · **Done**

Phase B. User-to-user transfer of wallet funds. The first feature that
actually moves money between users.

### Story 2.1 — POST /payments/p2p with overdraft prevention · Done

**Description:** Atomic peer-to-peer transfer between two users in the same tenant.

**Acceptance criteria:**
- `Idempotency-Key` header required (422 if missing)
- Recipient resolved by identifier (phone/email/etc.)
- Self-transfer rejected → 422 `self_transfer_not_allowed`
- Sender wallet must exist in requested currency → 404 `account_not_found`
- Cross-tenant recipient → 404
- Available balance check: `available_balance < amount` → 409 `insufficient_funds`
- Successful transfer creates a balanced two-leg ledger transaction
- 10 tests pass including the rejection paths

**PRD:** Pay-PRD-0250, 0220, 0200, 0060

### Story 2.2 — Concurrent double-spend protection via SELECT FOR UPDATE · Done

**Description:** Two simultaneous transfers from the same wallet for the full balance can only result in one success.

**Acceptance criteria:**
- Sender wallet row is locked (`SELECT ... FOR UPDATE`) during balance derivation
- Concurrent test (`test_p2p_concurrent_double_spend_blocked`) shows exactly one 201 and one 409 `insufficient_funds`
- Lock released on commit

**PRD:** Pay-PRD-0220 · **NFR:** 0100

### Story 2.3 — Internal top_up service + opening balances · Done

**Description:** Money enters the system from outside via `top_up`, which creates a `system_cash_inflow` account lazily.

**Acceptance criteria:**
- `top_up()` debits system_cash_inflow, credits user's financial_wallet
- Auto-creates system_cash_inflow account per (tenant, currency) on first use
- Seed gives Alice R 1000 + Bob R 500 as opening balances via top_up
- Re-running the seed doesn't double-credit (per-user idempotency key)

**PRD:** Pay-PRD-0320 (deferred public endpoint) · **Addendum:** system_cash_inflow

---

## Epic 3 — Kafka Rewards Inflow · **Done**

Phase C. External Kafka events drive rules evaluation; matching rules
credit user points accounts.

### Story 3.1 — External event source registration · Done

**Description:** Module 8 — registered event sources with optional shared_secret for HMAC.

**Acceptance criteria:**
- `POST /events/sources` returns 201 with source details
- Duplicate `source_key` → 409 (globally unique)
- Field mapping JSONB defaults to `'{}'`
- Status defaults to active

**PRD:** Pay-PRD-0495, 0510

### Story 3.2 — Event ingestion with dedup + tenant scoping · Done

**Description:** External event consumption via HTTP endpoint (Kafka consumer is a thin wrapper around the same service).

**Acceptance criteria:**
- `POST /events/external` accepts NormalisedEvent shape
- Unregistered source → ingestion log row with `status='REJECTED'`, no rule eval
- Duplicate `(source_key, external_event_id)` → ingestion log `DUPLICATE`, no side effect
- Source.tenant_id and event.tenant_id mismatch → REJECTED
- 7 tests including replay, unknown source, schema mismatch

**PRD:** Pay-PRD-0490, 0495, 0500, 0520

### Story 3.3 — Rules engine: first_time + milestone · Done

**Description:** Two of seven PRD rule types implemented; full schema for all 7 in place.

**Acceptance criteria:**
- `first_time` fires exactly once per user
- `milestone` counts qualifying events, fires at threshold, resets counter
- Inactive rules skipped
- Source-agnostic evaluation (Pay-PRD-0600)

**PRD:** Pay-PRD-0530–0617, 0570, 0580

### Story 3.4 — Reward issuance with double-issuance protection · Done

**Description:** Issuing a reward writes a `reward_events` row + a ledger transaction (DEBIT system_points_issuance → CREDIT user.points_account).

**Acceptance criteria:**
- UNIQUE INDEX on `(user_id, rule_id, triggering_event_id)` prevents double issue
- Code relies on the index — no check-then-insert (NFR-0110)
- Rejects when user has no points_account
- Rejects when tenant has no system_points_issuance account

**PRD:** Pay-PRD-0620 · **NFR:** 0110

### Story 3.5 — Rule CRUD admin endpoints · Done

**Description:** Test-only endpoints for creating rules in a tenant.

**Acceptance criteria:**
- `POST /rules` validates rule_type-specific fields
- `GET /rules` lists rules tenant-scoped
- Invalid rule config (e.g. milestone without count_threshold) → 422

**PRD:** Pay-PRD-0530–0617 (CRUD slice)

---

## Epic 4 — Redemption + Catalog · **Done**

Phase D. User converts earned points into cash via a registered redemption
provider. Catalog endpoints surface the user's full rewards story.

### Story 4.1 — Redemption provider registration · Done

**Description:** Each provider has one auto-created `provider_redemption_wallet`.

**Acceptance criteria:**
- `POST /redemption/providers` creates provider + wallet atomically
- `redemption_wallet_account_id` FK populated
- Configurable max_retries, retry_interval_secs, escalate_after_mins
- Tenant scoping enforced

**PRD:** Pay-PRD-0730 · **Addendum:** redemption_wallet_account_id

### Story 4.2 — Initiate redemption (two-legged PENDING) · Done

**Description:** Atomic PENDING ledger write with overdraft prevention.

**Acceptance criteria:**
- `POST /redemption/initiate` with required `Idempotency-Key` header
- Lock user.points_account → derive_balance → reject if insufficient
- Atomic two-leg PENDING: DEBIT user.points + CREDIT provider.wallet
- Concurrent double-spend blocked (test_initiate_concurrent_double_spend_blocked)
- Cross-tenant provider lookup → 404

**PRD:** Pay-PRD-0660, 0670, 0740 · **NFR:** 0100

### Story 4.3 — Confirm redemption (PENDING → COMPLETED) · Done

**Description:** Simulates provider success callback. Flips ledger entries.

**Acceptance criteria:**
- `POST /redemption/{id}/confirm` flips entries PENDING → COMPLETED
- Updates `transactions.status` and `redemptions.status`
- Records `external_reference` and `completed_at`
- Re-confirming already-COMPLETED → 409 `redemption_not_pending`
- Cross-tenant → 404

**PRD:** Pay-PRD-0690

### Story 4.4 — Fail redemption (PENDING → REVERSED) · Done

**Description:** Simulates provider failure. Flips ledger to REVERSED, restoring points.

**Acceptance criteria:**
- `POST /redemption/{id}/fail` with `reason` field required
- Flips entries PENDING → REVERSED
- REVERSED entries excluded from `derive_balance` → user's available balance restored
- Confirm-then-fail rejects → 409
- Cross-tenant → 404

**PRD:** Pay-PRD-0700

### Story 4.5 — Catalog summary endpoint · Done

**Description:** User-facing snapshot of points state.

**Acceptance criteria:**
- `GET /catalog/{user_id}/summary?tenant_id=...` returns available + reserved + lifetime_earned + lifetime_redeemed
- User without points_account → `{points: null}` (NOT 404)
- All numbers derived from ledger (not snapshot)
- Lifetime earned filters by `transaction_type='reward_issuance'` and COMPLETED status
- Lifetime redeemed filters by `transaction_type='redemption'` and COMPLETED status

**PRD:** Pay-PRD-0970

### Story 4.6 — Redemption history endpoint · Done

**Description:** Per-user redemption list newest first.

**Acceptance criteria:**
- `GET /catalog/{user_id}/redemption-history?tenant_id=...` newest first
- Tenant-scoped
- Returns all statuses (PENDING through MANUAL_REVIEW)

**PRD:** Pay-PRD-1030

### Story 4.7 — Points history endpoint (full audit trail) · Done

**Description:** Per-entry view of the user's points ledger with rule context for rewards.

**Acceptance criteria:**
- `GET /catalog/{user_id}/points-history?tenant_id=...` returns every ledger entry on the user's points_account
- Reward credits surface `rule_name` + `triggering_event_id` via reward_events join
- Redemption debits show `transaction_type='redemption'`
- Ordering: newest first
- Cross-tenant returns `[]` (no leak)

**PRD:** Pay-PRD-0980

---

## Epic 5 — Reconciliation + Admin UI · **In Progress**

Phase E. Closes the redemption lifecycle's "stale PENDING" gap and gives
operators a UI to see and act on the data.

### Story 5.1 — Sweep stale PENDING redemptions (Phase E.1) · Done

**Description:** Automated retry counter + escalation to MANUAL_REVIEW.

**Acceptance criteria:**
- `POST /reconciliation/sweep` with `threshold_minutes` parameter
- Finds PENDING redemptions older than cutoff
- Increments `retry_count` and updates `last_checked_at`
- When `retry_count >= provider.max_retries` → status MANUAL_REVIEW
- Returns counts (scanned, bumped, escalated, audit_entry_count)
- Ignores COMPLETED / FAILED / REVERSED redemptions
- Ignores recent (within-threshold) PENDING
- Writes one audit_log row per item touched

**PRD:** Pay-PRD-0750, 0790, 0800 · **NFR:** 0070 (sweep cadence — manual in E.1)

### Story 5.2 — Manual resolve from MANUAL_REVIEW (Phase E.1) · Done

**Description:** Operator terminates a MANUAL_REVIEW redemption with COMPLETED or REVERSED.

**Acceptance criteria:**
- `POST /reconciliation/{id}/resolve` with `outcome` and required `reason`
- COMPLETED: ledger entries PENDING → COMPLETED, balance permanently drops
- REVERSED: ledger entries PENDING → REVERSED, balance restored
- Rejects non-MANUAL_REVIEW status → 409
- Cross-tenant → 404
- Writes audit_log with full before/after JSONB snapshots

**PRD:** Pay-PRD-0780, 0790

### Story 5.3 — Audit log query (Phase E.1) · Done

**Description:** Read endpoint over the immutable audit_log table.

**Acceptance criteria:**
- `GET /reconciliation/audit?tenant_id=...&entity_type=&entity_id=&limit=`
- Tenant-scoped strictly
- Newest first
- Hard cap on limit (max 500)

**PRD:** Pay-PRD-0800 · **NFR:** 0160, 0250

### Story 5.4 — Provider status-check polling (Phase E.1+) · Backlog

**Description:** Real HTTP call to provider's `status_check_url` during sweep.

**Acceptance criteria:**
- Sweep calls provider's status_check_url for each PENDING
- TLS 1.2+ enforced (NFR-0260)
- Configurable timeout
- HMAC-verified response (paired with Phase F)
- Auto-confirm or auto-fail based on provider response

**PRD:** Pay-PRD-0720 · **Depends on:** Phase F (HMAC infra)

### Story 5.5 — Scheduled sweep via Celery beat (Phase E.1+) · Backlog

**Description:** Sweep runs every 15 minutes automatically instead of manual trigger.

**Acceptance criteria:**
- Celery beat job runs sweep every 15 min (NFR-0070)
- Configurable per tenant
- Job emits metrics: pending_count, escalated_count

**PRD:** Pay-PRD-0750 · **NFR:** 0070

### Story 5.6 — Admin UI shell (Phase E.2) · Backlog

**Description:** Next.js 16 AppShell — sidebar, topbar, command palette ⌘K, Keycloak login, tenant switcher.

**Acceptance criteria:**
- Keycloak login flow ends at admin home
- Sidebar with sections (Operations / Configuration / Audit)
- Command palette opens on ⌘K
- Tenant switcher in topbar (⌘T)
- Dark mode default, oklch tokens
- Per `docs/04-ui-layouts.md` §3 + §4

**Depends on:** Phase F (auth must be wired first)

### Story 5.7 — Admin pages: Users, Transactions, Reconciliation, Audit (Phase E.3) · Backlog

**Description:** The four operator-critical screens.

**Acceptance criteria:**
- Users: search by identifier, drawer detail, suspend action
- Transactions: paginated table with status pills, filters
- Reconciliation: PENDING + MANUAL_REVIEW queues, sweep trigger button, manual resolve drawer
- Audit log: filterable read view with JSON diff
- Per `docs/04-ui-layouts.md` §5

**Depends on:** Story 5.6

---

## Epic 6 — Authentication & Roles · **In Progress**

Phase F. Wires Keycloak JWT validation on admin endpoints, builds PIN/OTP
flow for end users, adds HMAC verification on provider callbacks, lands
Module 7 (Roles & Permissions).

### Story 6.1 — Keycloak JWT validation dependency (Phase F.1) · Done

**Description:** `get_current_admin()` validates Keycloak JWT signature + exp + iss. Extracts realm roles into a typed `AdminPrincipal`. `require_admin_role(role)` is the per-endpoint gate. Applied to all reconciliation endpoints as the pilot.

**Acceptance criteria:**
- ✓ Invalid signature → 401 `invalid_token`
- ✓ Expired token → 401 `token_expired`
- ✓ `alg: none` → 401 `invalid_algorithm`
- ✓ Unknown signing key → 401 `unknown_signing_key`
- ✓ Issuer mismatch → 401 `invalid_token`
- ✓ Public keys cached in-memory with 24h TTL + 60s refetch floor (DoS guard)
- ✓ Extracted role available via `AdminPrincipal.has_role()`
- ✓ Tested with real Keycloak-issued JWT end-to-end (`admin-test` user)

**Delivered:** 19 new auth tests + 32 existing reconciliation tests pre-authed via per-directory conftest. **110/110 total tests pass.**

**PRD:** Pay-PRD-0100 · **NFR:** 0170, 0180, 0210, 0260

### Story 6.2 — PIN/OTP user authentication flow · Backlog

**Description:** Module 1 user-side: register → OTP verify → PIN set → PIN auth.

**Acceptance criteria:**
- `POST /identity/otp/send`, `/otp/verify`, `/pin/set`, `/auth/pin`
- OTP bcrypt-hashed, single-use, expiry enforced (NFR-0170)
- PIN bcrypt-hashed (NFR-0170)
- Lockout after `PIN_MAX_ATTEMPTS` consecutive fails (NFR-0190)
- Session tokens issued to Redis only, never in DB
- Session timeout enforced (NFR-0180)

**PRD:** Pay-PRD-0020, 0030, 0040 · **NFR:** 0170, 0180, 0190

### Story 6.3 — Per-user Roles & Permissions (Module 7) · Backlog

**Description:** Platform-side roles distinct from Keycloak's operator roles.

**Acceptance criteria:**
- Migration adds `roles`, `role_permissions`, `user_roles` tables
- Role check is first step in payment orchestration (Pay-PRD-0260)
- Transaction without permitted role → 403 `not_authorised`
- Admin CRUD on roles

**PRD:** Pay-PRD-0440–0470 · **PRD:** Pay-PRD-0260 step 1

### Story 6.4 — Remove test-only body params (sender_user_id, tenant_id) · Backlog

**Description:** Every endpoint resolves the actor from the auth token instead of accepting it in the body.

**Acceptance criteria:**
- All existing endpoints stop accepting `sender_user_id` / `tenant_id` in body where applicable
- OpenAPI tags lose `test-only` suffix
- Tests updated to pass JWT in Authorization header

**PRD:** All previously-deferred residual risks across Phases A–E

### Story 6.5 — HMAC verification on provider callbacks · Backlog

**Description:** Provider webhook signature verification using `shared_secret`.

**Acceptance criteria:**
- Each event/provider source can carry a `shared_secret`
- HMAC-SHA256 verified with constant-time comparison
- Timestamp tolerance ≤ 5 min (prevent replay)
- Failed verification → 401 + audit log entry

**PRD:** Pay-PRD-0495 · **NFR:** 0210, 0260

### Story 6.6 — Audit log writes from every state-changing endpoint · Backlog

**Description:** Wire audit_log into payments, redemption, rules, etc.

**Acceptance criteria:**
- Every config change recorded (NFR-0250)
- Every transaction status transition recorded
- Actor resolved from auth (or 'system' for jobs)
- IP captured

**PRD:** NFR-0160, NFR-0250

---

## Epic 7 — Money Controls (Budgets + Limits + Pricing) · **Backlog**

Phase G. Pre-issuance guards: platform-side budget caps; per-tenant
transaction limits; transaction fees.

### Story 7.1 — Reward budgets table + pre-issuance check · Backlog

**Description:** Cap how much can be issued per (tenant, scope, currency, window).

**Acceptance criteria:**
- New `reward_budgets` table with scope_type, scope_id, currency, window_type
- `check_budget_available()` called inside `issue_points_reward` before ledger write
- Budget exceeded → 409 `budget_exceeded`
- 50/80/100% alert hooks

**Threat-modeled in:** earlier conversation on budget control

### Story 7.2 — Module 5: Limits & Thresholds · Backlog

**Description:** Per-tenant, per-transaction-type min/max + daily caps.

**Acceptance criteria:**
- `limit_configs` table; configurable per tenant + transaction_type
- Min/max per-transaction enforced before ledger write
- Daily count + value caps enforced
- Limit breach returns specific error_code
- Step 2 of Pay-PRD-0260 orchestration sequence

**PRD:** Pay-PRD-0330–0380 · **PRD:** Pay-PRD-0260 step 2

### Story 7.3 — Module 6: Pricing Engine · Backlog

**Description:** Fixed + variable fees per transaction type.

**Acceptance criteria:**
- `pricing_configs` table
- Fee calculated before ledger write (Pay-PRD-0400)
- Fee added as a debit leg in the same transaction
- Zero-fee transactions still call the pricing check (Pay-PRD-0420)
- Fee surfaced to user before confirmation in admin UI

**PRD:** Pay-PRD-0390–0430 · **PRD:** Pay-PRD-0260 step 3

### Story 7.4 — Admin UI for limits + pricing config · Backlog

**Description:** Editable tables in admin UI per `docs/04-ui-layouts.md` §5.6.

**Acceptance criteria:**
- Per-tenant table view of limits and pricing configs
- Inline edit on click
- Save triggers audit_log entry
- Cross-tenant config invisible

---

## Epic 8 — Notifications & Engagement · **Backlog**

Module 13 + Module 17. Internal SMS/push notifications; outbound events
to WebEngage.

### Story 8.1 — Transaction completion notification · Backlog
**PRD:** Pay-PRD-0810, 0840 · **Status:** Backlog

### Story 8.2 — Reward issuance notification · Backlog
**PRD:** Pay-PRD-0830 · **Status:** Backlog

### Story 8.3 — WebEngage outbound emitter (reward.issued, tier.changed, streak.broken, milestone.approaching) · Backlog
**PRD:** Pay-PRD-1060–1120 · **Status:** Backlog

---

## Epic 9 — Catalog Expansion · **Backlog**

Module 16 beyond Phase D's summary/history.

### Story 9.1 — Tier status + auto-progression · Backlog
**PRD:** Pay-PRD-0990 · **Status:** Backlog

### Story 9.2 — Badges (earned + locked display) · Backlog
**PRD:** Pay-PRD-1010 · **Status:** Backlog

### Story 9.3 — Active challenges · Backlog
**PRD:** Pay-PRD-1020 · **Status:** Backlog

### Story 9.4 — Next milestone nudges · Backlog
**PRD:** Pay-PRD-1000 · **Status:** Backlog

### Story 9.5 — Points expiry warnings · Backlog
**PRD:** Pay-PRD-1040 · **Status:** Deferred (Phase 1 PRD §5 non-goal)

---

## Epic 10 — Rules Engine Expansion · **Backlog**

The remaining 5 of 7 rule types from PRD Module 9.

### Story 10.1 — Streak rule type · Backlog
**PRD:** Pay-PRD-0615, 0616 · **Status:** Backlog

### Story 10.2 — Value-based rule type · Backlog
**PRD:** Pay-PRD-0618 · **Status:** Backlog

### Story 10.3 — Composite rule type (AND/OR) · Backlog
**PRD:** Pay-PRD-0619 · **Status:** Backlog

### Story 10.4 — Campaign rule type · Backlog
**PRD:** Pay-PRD-0621 · **Status:** Backlog

### Story 10.5 — Referral rule type · Backlog
**PRD:** Pay-PRD-0622 · **Status:** Backlog

### Story 10.6 — Bonus multipliers · Backlog
**PRD:** Pay-PRD-0623 · **Status:** Backlog

### Story 10.7 — Segment binding on rules + segments module · Backlog
**PRD:** Pay-PRD-0624 + Module 15 (Pay-PRD-0910–0960) · **Status:** Backlog

---

## Epic 11 — Hot-path Balance & Ledger Partitioning · **Backlog**

Phase H. Denormalised live balance for fast mobile-app reads + monthly
partitioning so the ledger can be archived/dropped without losing balance
correctness. Build this BEFORE the first real-tenant onboarding so we don't
re-architect under production traffic.

**Trigger conditions** (build when ANY is true):
- Median balance read > 50ms
- Any single account > 10k ledger entries
- Planning to drop ledger history for cost or regulatory reasons
- First real-tenant onboarding is imminent

### Story 11.1 — Live balance columns on accounts table · Backlog

**Description:** Add `balance` + `reserved_balance` as denormalised columns on `accounts`. These hold authoritative live state for user-owned accounts (`user_id IS NOT NULL`); system-owned accounts (`system_points_issuance`, `system_cash_inflow`, `provider_redemption_wallet`) keep the columns for symmetry but are best-effort — operator queries hit `derive_balance()` directly when they want truth.

**Acceptance criteria:**
- Migration adds `balance NUMERIC(20,6) NOT NULL DEFAULT 0` and `reserved_balance NUMERIC(20,6) NOT NULL DEFAULT 0` to `accounts`
- One-time backfill from `ledger_entries` per account (idempotent script)
- Convention documented: "user-owned accounts are authoritative; system accounts are advisory"

**PRD:** NFR-0030 (balance read < 2s) — this enables sub-50ms

### Story 11.2 — Atomic write-path refactor: post_transaction updates accounts.balance · Backlog

**Description:** Replace `SELECT FOR UPDATE → derive_balance → check → INSERT` with `UPDATE accounts SET balance = balance - X WHERE id = ? AND balance - reserved >= X` followed by `INSERT INTO ledger_entries`. Both in one DB transaction. Credits use the same UPDATE pattern but without the WHERE-clause overdraft check (additions are commutative — no lock needed beyond row-level UPDATE).

**Acceptance criteria:**
- Debit path: `UPDATE` is the overdraft check; 0 rows affected → `InsufficientFunds` raised, no ledger entry written
- Credit path: `UPDATE ... SET balance = balance + X` (no explicit lock)
- PENDING → COMPLETED transition: decrements `reserved_balance`
- PENDING → REVERSED transition: increments `balance` AND decrements `reserved_balance`
- All four cases in a single DB transaction
- Concurrent double-spend test from Phase B still passes (the new UPDATE pattern handles concurrency natively)

**PRD:** Pay-PRD-0220 (overdraft), Pay-PRD-0210 (reservation) · **NFR:** 0100

### Story 11.3 — Drift-detection invariant + daily Celery job · Backlog

**Description:** A daily background job that compares `accounts.balance` to `SUM(ledger_entries)` per account. Any mismatch is a P0 incident — page the on-call. Same query also runs as an invariant test at the end of every test session.

**Acceptance criteria:**
- Invariant test `test_accounts_balance_matches_ledger_sum` in `tests/invariants/`
- Celery beat job `reconcile_account_balances` runs every 24h
- Mismatch → write `audit_log` row with `action='balance.drift'` + before/after states
- Mismatch → emit alert (Slack/email — wired when notifications phase lands)
- Job NEVER auto-corrects — humans review every drift event

**PRD:** NFR-0100 (sum-to-zero) · **NFR:** 0160 (audit)

### Story 11.4 — PostgreSQL declarative partitioning on ledger_entries · Backlog

**Description:** Convert `ledger_entries` to a partitioned table by `created_at` (monthly). Existing data migrates into the current month's partition; new entries are routed automatically. Indexes are recreated per partition.

**Acceptance criteria:**
- Migration converts `ledger_entries` to `PARTITION BY RANGE (created_at)`
- 12 months of partitions pre-created (rolling window)
- `pg_partman` extension OR a Celery beat job creates next month's partition on the 1st of each month
- All existing tests pass against the partitioned table
- Query plan check: `EXPLAIN` on balance derivation shows partition pruning when `created_at` is in WHERE

**Operational note:** This is the most invasive migration in the project. Run on a maintenance window with a tested rollback.

### Story 11.5 — Partition-drop runbook + ledger archive summaries · Backlog

**Description:** Documented procedure for dropping old partitions safely. Before drop, the partition's per-account net effect is folded into a new `ledger_archive_summaries` table (account_id, period_start, period_end, net_change, debits_total, credits_total). After drop, this summary is the only record of activity in that period.

**Acceptance criteria:**
- New `ledger_archive_summaries` table (migration)
- Script `scripts/archive_partition.py` (idempotent, dry-run mode by default):
  1. SUM net effect per account for partition
  2. Verify total reconciles with `accounts.balance` ± delta of newer partitions
  3. Insert summary rows
  4. `DROP TABLE ledger_entries_<period>`
- Runbook in `docs/runbooks/partition-drop.md`
- Test: drop a partition, verify `accounts.balance` still correct and summary rows match

### Story 11.6 — Mobile balance read endpoint uses denormalised column · Backlog

**Description:** The `GET /api/v1/accounts/{id}/balance` endpoint (and `GET /catalog/{user}/summary`) reads `accounts.balance` directly instead of calling `derive_balance()`. 5×–100× faster on hot accounts.

**Acceptance criteria:**
- Endpoint latency benchmark: < 20ms at p95 even with 100k ledger entries on the account
- Tests verify the response matches `derive_balance()` (drift-test as a unit test)
- Caching layer (Redis) added as a thin wrapper IF the direct read isn't fast enough — measured first, not pre-cached

**PRD:** NFR-0030 (balance read < 2s — easily met) · **PRD:** Pay-PRD-0140

---

## Epic 12 — User Type Foundation · **Backlog**

User-types initiative. Introduces `user_type` as a first-class dimension on
users — `consumer`, `agent`, `super_agent`, `merchant`, `head_merchant` —
plus the shared plumbing Epics 13–17 build on. Merchants are modelled as
users (Decision D1); `parent_user_id` is stored now with commission logic
deferred (Decision D4). Import: `docs/LINEAR_BACKLOG_user_types.csv`.
Spec: `docs/superpowers/specs/2026-07-03-user-types-design.md`.

### Story 12.1 — user_type enum + column migration + backfill · Backlog

**Description:** Add PG enum `user_type` and a NOT NULL column on `users`.

**Acceptance criteria:**
- Enum values: consumer, agent, super_agent, merchant, head_merchant
- `users.user_type` NOT NULL default `consumer`; index `(tenant_id, user_type)`
- Migration backfills existing rows to `consumer`
- Migration test asserts backfill + enum/constraint integrity

**PRD:** Pay-PRD-0010, 0080

### Story 12.2 — parent_user_id self-FK + hierarchy validation · Backlog

**Description:** Nullable self-FK enabling agent→super_agent and merchant→head_merchant hierarchy, validated in the service layer.

**Acceptance criteria:**
- `agent` parent must be `super_agent`; `merchant` parent must be `head_merchant`; same tenant
- `consumer`/`super_agent`/`head_merchant` must have null parent
- Invalid pairing → 422 `user_type_invalid_parent`
- Tests cover each pairing

### Story 12.3 — Expose user_type + parent in identity schemas & detail · Backlog

**Description:** Surface `user_type` and `parent_user_id` in create/detail schemas and `GET /users/{id}`.

**Acceptance criteria:**
- Fields present in user create + detail Pydantic schemas
- Backwards compatible (defaults `consumer`)
- API test asserts round-trip

### Story 12.4 — PATCH /users/{id}/type with audit + idempotency · Backlog

**Description:** Admin endpoint to change a user's type with a mandatory reason.

**Acceptance criteria:**
- `platform-admin` only; body `{new_type, parent_user_id?, reason}`; reason mandatory; Idempotency-Key honoured
- Leaving a merchant type blocked while any `merchant_collection` balance ≠ 0 → `user_type_transition_blocked`
- Entering a merchant type requires a merchant profile
- Audit log records before/after + reason; emits `user.type_changed` post-commit
- Tests: happy, 401, 403, 422, tenant isolation, idempotency replay

**PRD:** Pay-PRD-0080 · **NFR:** 0170

### Story 12.5 — wallet.users.lifecycle topic + user.created/type_changed events · Backlog

**Description:** New Kafka topic and lifecycle events emitted after commit.

**Acceptance criteria:**
- Topic added to `config.Topics` and `kafka/topics.sh` (partitions 3, key `user_id`)
- Emit `user.created` + `user.type_changed` after DB commit; consumer idempotent via `event_ingestion_log`
- Tests: emit-after-commit, partition key, schema

**PRD:** Pay-PRD-0010 · **NFR:** 0130

### Story 12.6 — PRD Module 1 + glossary update for user types · Backlog

**Description:** Document the five user types in the source PRD.

**Acceptance criteria:**
- Module 1 documents the 5 types, hierarchy, and type-change flow; glossary (§3) updated
- New Pay-PRD IDs assigned; cross-refs added from Modules 5 (limits) and 6 (pricing)

---

## Epic 13 — Admin User Creation & Type Management · **Backlog**

Admin can create users (email or phone) with a `user_type` and change a
user's type from the admin portal — enabling the currently-disabled
"Register user" (Phase G) button. Backend hardening + admin-ui dialogs
following the Limits-page pattern.

### Story 13.1 — Harden POST /users: email-or-phone, user_type, parent, merchant profile · Backlog

**Description:** Extend the admin create endpoint for the new dimensions.

**Acceptance criteria:**
- At least one identifier (email or phone) required → else `identifier_required`
- Accepts `user_type` (default consumer), `parent_user_id`, and a merchant profile payload for merchant types
- Idempotency-Key honoured; audit logged
- Tests: happy (email-only, phone-only, both), 422 no-identifier, tenant isolation, idempotency

**PRD:** Pay-PRD-0010, 0050, 0080

### Story 13.2 — Admin create-user dialog · Backlog

**Description:** Create-user dialog on the Users page (enables the disabled Register-user button).

**Acceptance criteria:**
- Identifier type toggle (email/phone), profile fields, `user_type` selector
- Parent picker shown for agent/merchant types; merchant-profile fields for merchant types
- Server action returns `{ok} | {ok:false, errorCode, message}` + `revalidatePath`
- Follows the Limits `CreateLimitDialog` pattern

### Story 13.3 — Change-type action + confirm/reason modal on user detail · Backlog

**Description:** Change a user's type from the detail card.

**Acceptance criteria:**
- Confirm modal requires a reason; calls `PATCH /users/{id}/type`
- Hidden below `platform-admin`; shows/links parent when set
- Surfaces `user_type_transition_blocked` and invalid-parent errors

### Story 13.4 — User-type badge + filter on users list · Backlog

**Description:** Show and filter by user type.

**Acceptance criteria:**
- `user_type` badge on detail + lookup results
- Filter users by type; reuses StatusPill-style component

### Story 13.5 — Server actions + API client wiring for create/change-type · Backlog

**Description:** Wire the admin-ui data layer.

**Acceptance criteria:**
- `createUserAction` + `changeUserTypeAction` server actions
- Typed API client functions + `UserType` TS type mirroring the Pydantic enum in `api-endpoints.ts`/`api-types.ts`

---

## Epic 14 — External User-Creation API · **Backlog**

Externally callable, OpenAPI-documented user-creation API for partners.
Per-tenant API keys + HMAC request signing (Decision D3, reuses
`auth/hmac.py`). Rate limited, idempotent, tenant derived from the key.
Security-reviewed before merge.

### Story 14.1 — api_keys model + migration · Backlog

**Description:** Storage for per-tenant API keys.

**Acceptance criteria:**
- `api_keys`: tenant_id, key_id, secret_hash (never plaintext), status, created_at, last_used_at
- Secret shown once on creation; tenant-scoped
- Migration + tenant isolation test

### Story 14.2 — API key management UI on Tenants screen · Backlog

**Description:** Manage keys from the existing Tenants detail tabs.

**Acceptance criteria:**
- API keys tab: create (show secret once), list, revoke
- Follows existing tenant-tabs layout

### Story 14.3 — API-key + HMAC auth dependency · Backlog

**Description:** FastAPI dependency authenticating external callers.

**Acceptance criteria:**
- Verifies `X-Sasai-Api-Key` + `X-Sasai-Signature` (HMAC-SHA256, `t=<unix>,v1=<hex>`, 300s replay window via `auth/hmac.py`)
- Resolves tenant from the key
- Error codes: `api_key_invalid`, `signature_invalid`, `signature_replayed`
- Tests: valid, bad key, bad signature, replayed, expired timestamp

**NFR:** 0210

### Story 14.4 — POST /api/v1/external/users · Backlog

**Description:** Partner-facing create-user endpoint.

**Acceptance criteria:**
- Same semantics as admin create; tenant from API key (never from payload); email or phone; Idempotency-Key required
- Reuses `identity.create_user`
- Tests: happy, auth failures, 422, idempotency, cross-tenant rejection

**PRD:** Pay-PRD-0010, 0050

### Story 14.5 — Per-key rate limiting (Redis) · Backlog

**Description:** Throttle external callers per key.

**Acceptance criteria:**
- Per-API-key token bucket in Redis; exceed → 429 `rate_limited`
- Test asserts limit + reset

### Story 14.6 — Curated OpenAPI external tag + exported partner spec · Backlog

**Description:** Partner-ready API documentation.

**Acceptance criteria:**
- External endpoints tagged; curated request/response examples + `{error_code, message}` envelope
- Exported partner OpenAPI spec checked into `docs/`

### Story 14.7 — Security review: external surface (STRIDE + OWASP API) · Backlog

**Description:** Adversarial review of the new external surface.

**Acceptance criteria:**
- `security` agent: STRIDE threat model + OWASP API Top 10 pass on API keys, HMAC, rate limiting, external create
- Sign-off required before merge (auth + money + PII trigger)

---

## Epic 15 — Type-Aware Limits · **Backlog**

Make limit configs resolvable by `user_type`. Add a nullable `user_type` to
`limit_configs` and `wallet_limit_configs` (NULL = default for all types);
an exact-type row beats the default at enforcement. Extends the
WAL-233…238 limits work.

### Story 15.1 — Add nullable user_type to limit_configs + wallet_limit_configs · Backlog

**Description:** Schema change adding the new dimension to both limit tables.

**Acceptance criteria:**
- Nullable `user_type` on both tables; unique constraints extended with `user_type` using `NULLS NOT DISTINCT` (or paired partial unique indexes if local PG < 15 — decided in the migration)
- Tenant isolation preserved; migration test

### Story 15.2 — Resolution precedence in limit enforcement · Backlog

**Description:** Enforcement prefers a type-specific row over the default.

**Acceptance criteria:**
- Resolves exact (existing dims + caller `user_type`) first, else the `user_type IS NULL` default (`ORDER BY user_type NULLS LAST LIMIT 1`)
- Applies to both service and wallet limits; no per-user overrides

### Story 15.3 — Limits CRUD schema + router updates for user_type · Backlog

**Description:** Expose the dimension through the admin API.

**Acceptance criteria:**
- Optional `user_type` on create schemas + list/delete filters; validated against the enum
- API tests

### Story 15.4 — Limits UI: user_type column + selector · Backlog

**Description:** Surface the dimension on the Limits page.

**Acceptance criteria:**
- `user_type` column ("All types" when NULL) + selector in create dialogs

### Story 15.5 — Precedence matrix tests for limits · Backlog

**Description:** Prove the resolution rules.

**Acceptance criteria:**
- Tests for typed row vs NULL default vs no config, across service and wallet limits

---

## Epic 16 — Type-Aware Pricing · **Backlog**

Make pricing/fees resolvable by `user_type`. Add a nullable `user_type` to
`pricing_configs`; `quote_fee` resolves an exact-type row first, else the
default. Mirrors Epic 15 for fees.

### Story 16.1 — Add nullable user_type to pricing_configs · Backlog

**Description:** Schema change adding the dimension to pricing.

**Acceptance criteria:**
- Nullable `user_type` on `pricing_configs`; unique constraint extended (`NULLS NOT DISTINCT` or paired partial indexes)
- Migration + tenant isolation test

### Story 16.2 — quote_fee precedence resolution by user_type · Backlog

**Description:** Fee resolution prefers a type-specific row.

**Acceptance criteria:**
- Resolves exact (existing dims + `user_type`) first, else `user_type IS NULL` default (`ORDER BY user_type NULLS LAST LIMIT 1`)
- Fee still quoted before the ledger write

**PRD:** Pay-PRD-0260

### Story 16.3 — Pricing CRUD schema + router updates for user_type · Backlog

**Description:** Expose the dimension through the admin API.

**Acceptance criteria:**
- Optional `user_type` on the pricing create schema + list/delete filters; validated against the enum
- API tests

### Story 16.4 — Pricing UI: user_type column + selector · Backlog

**Description:** Surface the dimension on the Pricing page.

**Acceptance criteria:**
- `user_type` column ("All types" when NULL) + selector in the create dialog

### Story 16.5 — Precedence matrix tests for pricing · Backlog

**Description:** Prove the fee resolution rules.

**Acceptance criteria:**
- Tests for typed row vs NULL default vs no config in `quote_fee`

---

## Epic 17 — Airtime Merchant Vertical · **Backlog**

First merchant vertical. An airtime merchant collects user funds into a
`merchant_collection` ledger account, then provisions airtime via an
external provider after commit. Uses merchants-as-users (D1) and builds on
the existing `AirtimeRecharge` model and `airtime_merchant_holding`
groundwork. Depends on Epics 12, 15, 16.

### Story 17.1 — merchant_profiles model + migration · Backlog

**Description:** Business-profile extension for merchant users.

**Acceptance criteria:**
- One-to-one with merchant/head_merchant users: user_id PK/FK, tenant_id, business_name, category, `provider_config` JSONB, settlement fields, timestamps
- Created transactionally with the user or on type change into a merchant type
- Migration + tenant isolation test

### Story 17.2 — merchant_collection account type + provisioning · Backlog

**Description:** Ledger account that collects merchant funds.

**Acceptance criteria:**
- New `merchant_collection` account type constant
- One account per (tenant, merchant user, merchant_collection, currency) provisioned on profile creation via the existing partial unique index
- Reuses `accounts.user_id` ownership

### Story 17.3 — Airtime purchase flow: double-entry + pricing + limits · Backlog

**Description:** The buy-airtime money movement.

**Acceptance criteria:**
- One transaction: debit consumer `financial_wallet`, credit merchant `merchant_collection`, fee legs to `system_fee_collected` via type-aware pricing
- Limits enforced with the consumer's `user_type`; `AirtimeRecharge` created PENDING and linked to the transaction; Idempotency-Key
- Ledger-invariant tests (entries balance, append-only)

**PRD:** Pay-PRD-0310 · **NFR:** 0100

### Story 17.4 — Provider adapter interface + Celery provisioning task · Backlog

**Description:** External airtime provisioning after commit.

**Acceptance criteria:**
- After DB commit, a Celery task calls the provider via an adapter interface (config from `merchant_profiles.provider_config`)
- Success → recharge COMPLETED + event; bounded retries with backoff
- External call never inside the DB transaction

**NFR:** 0130

### Story 17.5 — Failure reversal path + reconciliation hook · Backlog

**Description:** Make failed provisioning safe and observable.

**Acceptance criteria:**
- On failure after retries: append a reversal transaction (merchant_collection → consumer wallet; ledger stays append-only); recharge FAILED/REVERSED
- Stuck PENDING recharges surface in the existing reconciliation queue
- Reversal ledger-invariant test (net-zero)

### Story 17.6 — Events + ledger-invariant tests for airtime flow · Backlog

**Description:** Eventing and test coverage for the vertical.

**Acceptance criteria:**
- Provisioning outcomes ride `wallet.transactions.completed` with recharge status
- Tests: ledger sum-to-zero, append-only, reversal correctness, idempotency, tenant isolation

---

## Summary

| Epic | Status | Stories | Done | Backlog |
|---|---|---|---|---|
| 1. Foundation | Done | 6 | 6 | 0 |
| 2. P2P Transfer | Done | 3 | 3 | 0 |
| 3. Kafka Rewards Inflow | Done | 5 | 5 | 0 |
| 4. Redemption + Catalog | Done | 7 | 7 | 0 |
| 5. Reconciliation + Admin UI | In Progress | 7 | 3 | 4 |
| 6. Auth & Roles | In Progress | 6 | 1 | 5 |
| 7. Money Controls | Backlog | 4 | 0 | 4 |
| 8. Notifications & Engagement | Backlog | 3 | 0 | 3 |
| 9. Catalog Expansion | Backlog | 5 | 0 | 5 |
| 10. Rules Engine Expansion | Backlog | 7 | 0 | 7 |
| 11. Hot-path Balance & Ledger Partitioning | Backlog | 6 | 0 | 6 |
| 12. User Type Foundation | Backlog | 6 | 0 | 6 |
| 13. Admin User Creation & Type Management | Backlog | 5 | 0 | 5 |
| 14. External User-Creation API | Backlog | 7 | 0 | 7 |
| 15. Type-Aware Limits | Backlog | 5 | 0 | 5 |
| 16. Type-Aware Pricing | Backlog | 5 | 0 | 5 |
| 17. Airtime Merchant Vertical | Backlog | 6 | 0 | 6 |
| **Total** | — | **93** | **25** | **68** |

**~27% delivered** by story count. Money-movement loop (earn → hold →
redeem → reconcile) is complete and the first auth gate (Keycloak admin JWT
validation, Phase F.1) is live on reconciliation endpoints. Remaining
auth work covers user PIN/OTP, roles module, HMAC, and applying auth gates
across the rest of the admin surface.

The **user-types initiative** (Epics 12–17) adds five user types
(consumer/agent/super_agent/merchant/head_merchant) driving type-aware
pricing and limits, admin + external user creation, and the first merchant
vertical (airtime). New items import via `docs/LINEAR_BACKLOG_user_types.csv`;
design in `docs/superpowers/specs/2026-07-03-user-types-design.md`.
