# Data Architecture

> System-level summary — the authoritative per-module implementation is in [docs/design/](design/README.md); requirements are in [docs/02-prd.md](02-prd.md). Last refreshed 2026-08-05.

> **Document type:** Data Architecture
> **Version:** 0.2 (refreshed against `main`)
> **Date:** 2026-05-28 · refreshed 2026-08-05
> **Deep design:** ledger + account model in [design/02-ledger-accounts-and-money-movement.md](design/02-ledger-accounts-and-money-movement.md); events/outbox in [design/06-events-ingestion-and-mode-awareness.md](design/06-events-ingestion-and-mode-awareness.md).

---

## 1. Core entity map

One SQLAlchemy ORM file per domain under `backend/app/shared/models/` (~30 files). Per-module DDL detail lives in the [design docs](design/README.md).

| Domain | Tables |
|---|---|
| Tenant / config | `tenants` (carries `business_type`), `tenant_config` |
| Identity | `users`, `user_identifiers`, `user_profiles`, `otp_requests`, `auth_attempts`, `merchant_profiles`, `admin_profiles` |
| Roles | `roles`, `role_permissions`, `user_roles` |
| Accounts | `accounts` (11 account types), `account_balance_snapshots` |
| Ledger | `transactions`, `ledger_entries` |
| Money controls | `limit_configs`, `wallet_limit_configs`, `pricing_configs`, `tax_configs`, `commission_configs`, `step_up_policies`, `reward_budgets` |
| Catalog / access | `instruments` (currencies), `services` (transaction types + access policy) |
| Rules | `rules`, `rule_conditions`, `user_rule_progress`, `bonus_multipliers`, `bonus_multiplier_rules` |
| Rewards | `reward_events`, `reward_outbox` (internal wallet→rewards, `both` mode), badges/tiers/points-expiry (schema only, surfaces Planned) |
| Redemption | `redemption_providers`, `redemptions` |
| Events | `external_event_sources`, `event_ingestion_log` |
| Segments | `segments`, `segment_groups`, `user_segments` |
| Referrals | `referral_codes`, `referrals` |
| Governance (maker-checker) | `config_requests`, `money_operations`, `user_operations` (+ per-subsystem review rows) |
| Partner API | `api_keys`, `external_user_creations` |
| Audit | `audit_log` |

Notes: `reward_outbox` is a transactional outbox, not Kafka. Rewards catalog extras (tiers, badges, challenges, points-expiry) have schema but no live user surface. Module 13 `notifications` is **not built** (no table). Full HOW per domain in [docs/design/](design/README.md).

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

**One choke point.** Every value movement funnels through `ledger.service.post_transaction`; nothing writes `ledger_entries` any other way. Its `FOR UPDATE` balance guard (invariant #11) locks only **`financial_wallet`** and the **`system_cash_inflow`** cash-float rows (in id-sorted order, before any balance read, held through commit) and enforces overdraft, the `max_balance` ceiling (user wallet only), and the non-negative float floor; all pool/collection/points accounts are skipped. Reversals and earned payouts are cap-exempt. Fee/limit config is fail-closed before the write (`require_pricing_and_limits` → 422). In `both`-mode tenants, `post_transaction` also writes the `reward_outbox` row atomically with the ledger commit. Full detail: [design/02-ledger-accounts-and-money-movement.md](design/02-ledger-accounts-and-money-movement.md).

---

## 4. Account types

`accounts.account_type` — **11 types** (`backend/app/shared/models/accounts.py`, `ACCOUNT_TYPES`). Only the two **guarded** types below (`financial_wallet`, `system_cash_inflow`) are subject to the ledger balance guard; all others are pool / collection / mirror / points accounts and are skipped by it.

| Type | Holds | Owner | Guarded? |
|---|---|---|---|
| `financial_wallet` | Monetary balance in `currency` | User or merchant | ✅ overdraft + `max_balance` |
| `system_cash_inflow` | Operator **cash float** — money entering from the bank, source of user funding | System (one per tenant per currency) | ✅ overdraft **floor** (`InsufficientFloat`), no ceiling |
| `points_account` | Reward points balance | User | — |
| `system_points_issuance` | Master source of all reward points (debit side when issuing) | System (`user_id = NULL`) | — |
| `provider_redemption_wallet` | Points in-flight to a redemption partner | System (platform-held) | — |
| `airtime_merchant_holding` | Airtime merchant collection account | System (merchant) | — |
| `operator_adjustment` | Bank mirror — counter-leg for float top-ups / withdrawals (trends negative) | System | — |
| `system_fee_collected` | Collected operator fees | System | — |
| `commission` | Agent commission collected | System | — |
| `tax_service_collected` | Tax on service fee | System | — |
| `tax_commission_collected` | Tax on commission | System | — |

A single user can hold multiple accounts: one `financial_wallet` per currency + one `points_account` per tenant. System/collection accounts are lazily provisioned per tenant (and per currency where relevant).

### Balance invariant — `system_points_issuance`

The PRD requires double-entry balance (NFR-0100) and credits to a user's `points_account` on rule fire (Pay-PRD-0620), but never names what the offsetting DEBIT is. For the ledger to sum to zero, every CREDIT to a user must have a corresponding DEBIT somewhere.

**Decision:** Each tenant has exactly one `system_points_issuance` account. Reward issuance posts:
- DEBIT `system_points_issuance` (the master source)
- CREDIT user's `points_account`

The system_points_issuance balance trends increasingly negative as more points are issued. This is by design — a negative balance here equals "points outstanding in user accounts + provider wallets". When a user redeems, points flow user → provider_redemption_wallet (no change to system_points_issuance). When a provider settles a redemption, points are effectively "burnt" — modelled as DEBIT user_redemption_wallet → CREDIT system_points_issuance (returns to zero).

**Invariant:** `system_points_issuance.balance + SUM(all points_account balances) + SUM(provider_redemption_wallet balances) == 0` at all times.

Each tenant auto-creates one `system_points_issuance` account on tenant creation.

### Balance invariant — `system_cash_inflow` (the operator cash float)

The money counterpart of `system_points_issuance`: the offsetting account for money entering
a user wallet (funding, cash-in, cashback). One per tenant **per currency**, lazily provisioned.

It is a **POSITIVE** balance carrying a non-negative overdraft **floor** enforced at the ledger
choke point (`post_transaction`, invariant #11). It must be pre-funded from the bank — CREDIT
`system_cash_inflow` / DEBIT an `operator_adjustment` bank mirror (e.g. via
`treasury.adjust_system_wallet`) — before it can fund users. A net DEBIT that would drive it
below zero is rejected with `InsufficientFloat` (409). It has no `max_balance` ceiling, so a
top-up credit is never blocked; a fund reversal credits it back (never floored). The float
does **not** trend negative:

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

## 6. Event → reward data flow

Two mode-gated sources feed the same evaluate-and-issue core (`evaluate_and_issue_firings`); there is **no internal Kafka producer** and **no engagement emission** (Module 17 gap).

**External (`rewards` mode only)** — over `wallet.events.external` (Kafka) or the equivalent HTTP endpoint:
```
Event arrives ─► source registered? (external_event_sources) ─► mode gate (external_events_allowed)
              ─► HMAC proof-of-origin (Pay-PRD-0495) ─► dedup (event_ingestion_log on source_key+external_event_id)
              ─► normalise (field_mapping JSONB) ─► evaluate active rules ─► issue reward (ledger + reward_events)
```

**Internal (`both` mode only)** — a completed rewardable wallet transaction writes a `reward_outbox` row **atomically with the ledger commit** (inside `post_transaction`); a post-commit fast path plus a 60s Celery sweep drain it into the same evaluate-and-issue core. No Kafka. Absolutely fail-open — rewards never break the money path.

The `reward_events` `UNIQUE INDEX (user_id, rule_id, triggering_event_id)` is the structural guarantee against double-issuance (NFR-0110); dedup upstream (event_ingestion_log / outbox `transaction_id`) prevents re-evaluation.

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
