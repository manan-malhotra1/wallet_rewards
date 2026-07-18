# Data Architecture

> **Document type:** Data Architecture
> **Version:** 0.1
> **Date:** 2026-05-28
> **Source of truth for schemas:** Technical PRD §6 at `/Users/manan/Downloads/wallet-platform-technical-prd-v1_0.md`

---

## 1. Core entity map (17 tables)

| Domain | Tables |
|---|---|
| Tenant | `tenants`, `tenant_config` |
| Identity | `users`, `user_identifiers`, `user_profiles`, `otp_requests`, `auth_attempts` |
| Merchant | `merchants` |
| Roles | `roles`, `role_permissions`, `user_roles` |
| Accounts | `accounts`, `account_balance_snapshots` |
| Ledger | `transactions`, `ledger_entries` |
| Limits / Pricing | `limit_configs`, `pricing_configs` |
| Rules | `rules`, `rule_conditions`, `user_rule_progress`, `bonus_multipliers`, `bonus_multiplier_rules` |
| Rewards | `reward_events`, `badges`, `user_badges`, `tiers`, `user_tier_history`, `points_expiry_rules` |
| Redemption | `redemption_providers`, `redemptions` |
| Events | `external_event_sources`, `event_ingestion_log` |
| Segments | `segments`, `segment_members`, `segment_upload_history` |
| Notifications / Audit | `notifications`, `audit_log` |
| Referrals | `referral_codes`, `referrals` |

Full DDL in Technical PRD §6.1–6.14.

---

## 2. Foundational design rules

1. **UUID primary keys** (`gen_random_uuid()`) on every table — avoids ID enumeration.
2. **All timestamps `TIMESTAMPTZ`** — never `TIMESTAMP`. Always store UTC, present local.
3. **Soft deletes via `deleted_at TIMESTAMPTZ NULL`** — never hard-delete user/financial data.
4. **`tenant_id` on every domain table** — application-layer enforced isolation.
5. **Money / points use `NUMERIC(20, 6)`** — never `FLOAT`. Currency code stored separately as `CHAR(3)`.
6. **Idempotency** — every `transactions` row carries a unique-per-tenant `idempotency_key`.
7. **Indexes on every FK** plus columns used in WHERE/ORDER BY (see Technical PRD for exact index list).
8. **No triggers, no stored procedures.** All logic in application code, all schema via Alembic.

---

## 3. The ledger — the most important data structure

```
transactions                       ledger_entries
─────────────                      ──────────────
id                                 id
tenant_id                          transaction_id ──┐
idempotency_key (unique/tenant)    account_id        │
transaction_type                   entry_type (DEBIT/CREDIT)
status (PENDING/COMPLETED/         amount              │
        FAILED/REVERSED)           currency             │
amount                             status                │
fee_amount                         created_at            │  No updated_at —
currency                                                  │  entries are
external_reference                                        │  IMMUTABLE
external_status                                           │  Reversal = new entry
retry_count                                               │
created_at                                                │
updated_at                                                │
                                                          │
                  account_balance_snapshots               │
                  ─────────────────────────                │
                  id                                       │
                  account_id                                │
                  balance (derived: SUM(ledger_entries))    │
                  reserved_balance                          │
                  snapshot_at                              │
                  last_ledger_entry_id ─────────────────────┘
                                                            ▲
                                                            │
                                              Snapshot is a READ optimisation
                                              ONLY. Authoritative balance is
                                              always SUM(ledger_entries).
```

### Invariants the schema enforces (and we enforce in code on top)

- `ledger_entries` has no `updated_at` — DB enforces immutability by convention; code enforces it by never issuing UPDATE statements against this table.
- Every `transaction` has ≥ 2 `ledger_entries` (one DEBIT, one CREDIT) — double-entry preserved.
- Sum of all `ledger_entries.amount` across DEBIT minus CREDIT = 0 system-wide (NFR-0100). Invariant test in CI.
- `transactions.idempotency_key` UNIQUE per `tenant_id` (Pay-PRD-0200).
- `status` transitions enforced in app code: `PENDING → COMPLETED | FAILED | REVERSED`. No transitions out of terminal states.

---

## 4. Account types

`accounts.account_type` enum (extended from PRD §6.5 — see addendums below):

| Type | Holds | Owner |
|---|---|---|
| `financial_wallet` | Monetary balance in `currency` | User or merchant |
| `points_account` | Reward points balance | User |
| `system_points_issuance` | Master source of all reward points (debit side when issuing) | System (`user_id = NULL`, `merchant_id = NULL`) |
| `provider_redemption_wallet` | Points in-flight to a redemption partner | System (platform-held) |
| `system_cash_inflow` | Master source of money entering the system from outside (top-ups, external receipts) | System (one per tenant per currency) |

A single user can hold multiple accounts: one `financial_wallet` per currency + one `points_account` per tenant.

### Addendum — `system_points_issuance` (added 2026-05-28)

The PRD requires double-entry balance (NFR-0100) and credits to a user's `points_account` on rule fire (Pay-PRD-0620), but never names what the offsetting DEBIT is. For the ledger to sum to zero, every CREDIT to a user must have a corresponding DEBIT somewhere.

**Decision:** Each tenant has exactly one `system_points_issuance` account. Reward issuance posts:
- DEBIT `system_points_issuance` (the master source)
- CREDIT user's `points_account`

The system_points_issuance balance trends increasingly negative as more points are issued. This is by design — a negative balance here equals "points outstanding in user accounts + provider wallets". When a user redeems, points flow user → provider_redemption_wallet (no change to system_points_issuance). When a provider settles a redemption, points are effectively "burnt" — modelled as DEBIT user_redemption_wallet → CREDIT system_points_issuance (returns to zero).

**Invariant:** `system_points_issuance.balance + SUM(all points_account balances) + SUM(provider_redemption_wallet balances) == 0` at all times.

Each tenant auto-creates one `system_points_issuance` account on tenant creation.

### Addendum — `system_cash_inflow` (added 2026-05-28, Phase B)

Mirror of `system_points_issuance` for **money** rather than points. Used as the offsetting
debit when external money enters the system: top-ups, mobile money receipts, bank credits.

Without this account type, the seed cannot post opening balances to user wallets in a way
that preserves the sum-to-zero invariant (NFR-0100). The future top-up endpoint
(Pay-PRD-0320) uses the same account.

Each tenant has one `system_cash_inflow` account **per currency** (so a multi-currency
tenant has multiple — one for ZAR, one for KES, etc.). Phase B seeds it lazily on first
top-up.

**Amendment — no-overdraft float floor (2026-07-18).** The float is now a **POSITIVE**
balance carrying a non-negative overdraft floor enforced at the ledger choke point
(`post_transaction`, invariant #11). It must be pre-funded from the bank — CREDIT
`system_cash_inflow` / DEBIT an `operator_adjustment` bank mirror (e.g. via
`treasury.adjust_system_wallet`) — before it can fund users. A net DEBIT that would drive
it below zero is rejected with `InsufficientFloat` (409). The old convention where the
float trended negative (mirroring `system_points_issuance`) is **replaced**:

```
# OLD (pre-2026-07-18): system_cash_inflow.balance + SUM(financial_wallets, that ccy) == 0
# NOW: system_cash_inflow.balance == bank_injected − user_funded ≥ 0
```

The counter-leg for the bank injection is the `operator_adjustment` bank mirror (which
trends negative as cash leaves the bank), so system-wide sum-to-zero (NFR-0100) still
holds across the float + mirror + wallets. The seed pre-funds the float from the bank
mirror before posting any user opening balance.

---

## 5. Multi-tenancy

**Pattern:** `tenant_id UUID NOT NULL REFERENCES tenants(id)` on every domain table. Resolved from the authenticated token on every request. Indexed.

**Verified at:**
- Application: every query filters by `tenant_id` from the session context. We will add a SQLAlchemy event hook that injects `tenant_id` into every SELECT/INSERT/UPDATE — see `backend/app/database.py`.
- Tests: a `test_tenant_isolation_for_<table>` test for every domain table that proves cross-tenant reads return zero rows.

**Future:** Move to PostgreSQL Row-Level Security when compliance audit demands defense-in-depth at the DB layer (probably Phase 2 once we have a paying enterprise tenant).

---

## 6. Event ingestion data flow

```
External event arrives  ──► Validate source registered (external_event_sources)
                            Verify proof-of-origin
                            Deduplicate (event_ingestion_log on source_key + external_event_id)
                            Normalise via field_mapping JSONB
                            Emit to Kafka topic wallet.events.normalised
                            Rules engine consumes
                            On qualifying event, write reward_events (UNIQUE on user_id+rule_id+triggering_event_id)
                            Atomic ledger_entries + transactions row for the reward credit
                            Emit wallet.rewards.issued
                            Engagement emitter relays to wallet.engagement.outbound → WebEngage
```

The `reward_events` table's `UNIQUE INDEX (user_id, rule_id, triggering_event_id)` is the structural guarantee against double-issuance (NFR-0110).

---

## 7. Caching strategy

| What | Where | TTL | Invalidation |
|---|---|---|---|
| User identifier → user_id resolution | Redis | 1h | On identifier add/remove/verify |
| Active rules for tenant | Redis | 5m | On rule create/update/deactivate |
| Account balance (display only) | Redis | 30s | On any ledger entry for that account |
| Segment membership (estimated count) | Redis | 1h | On segment recompute |
| Keycloak public keys (JWT verify) | In-memory | 24h | On Keycloak realm change |

**Never cache:** transaction status (always fresh from DB), available balance for write checks (always derived live), idempotency keys (always DB lookup).

---

## 8. Sensitive data handling

| Field | Storage | Logging |
|---|---|---|
| `users.pin_hash` | bcrypt (passlib) | Never in logs, never in API responses |
| `otp_requests.otp_hash` | bcrypt | Never in logs |
| `user_identifiers.identifier_value` (phone/email) | Plaintext (functional requirement) | Masked in logs: `+27 82 *** 0142` |
| `auth_attempts.ip_address` | Plaintext | Logged for audit |
| Session tokens | Redis only (never DB) | Never logged |
| Keycloak client secrets | Env var (vault in prod) | Never in code, never in logs |

---

## 9. Retention

| Data | Retention | Mechanism |
|---|---|---|
| `ledger_entries`, `transactions` | 7 years minimum (NFR-0150) | No DELETE; immutable |
| `audit_log` | 7 years minimum | Immutable; no `updated_at` |
| `auth_attempts` | 1 year then archive | Background job |
| `otp_requests` | 30 days then purge | Background job; PII minimisation |
| `notifications` | 1 year | Background job |
| `event_ingestion_log` | 90 days | Background job; only the dedup window matters |

---

## 10. Backup & recovery

| Concern | Approach |
|---|---|
| Backups | PostgreSQL automated daily + WAL archiving for point-in-time recovery |
| Retention of backups | 90 days |
| RPO (data loss tolerance) | 5 minutes (WAL shipping) |
| RTO (downtime tolerance) | 1 hour at growth, 4 hours at MVP |
| Recovery drill | Quarterly — restore a snapshot into a sandbox, validate ledger sum-to-zero |
