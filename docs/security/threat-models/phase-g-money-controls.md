# Threat Model — Phase G Money Controls (Budgets · Limits · Pricing)

> **Date:** 2026-06-16
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0260 (orchestration), 0330–0380 (limits),
> 0390–0430 (pricing), §4.3 (budgets — internal extension)
> **Code reference:** `app/modules/budgets/`, `app/modules/limits/`,
> `app/modules/pricing/`, integration points in
> `app/modules/payments/service.py` + `app/modules/rewards/service.py`
> **Linear:** WAL-50, WAL-51, WAL-52, WAL-53

---

## 1. What this phase delivers

Three independent control planes that gate every money/points movement
BEFORE it touches the ledger. Each one is the answer to a different
question:

| Question | Control |
|---|---|
| "Can the platform afford to issue this reward?" | **Budget** (WAL-50) |
| "Is this user/tenant allowed to move this much?" | **Limit** (WAL-51) |
| "How much does this transaction cost the user?" | **Pricing** (WAL-52) |

Together they implement steps 2–3 of the PRD's payment orchestration
sequence (`Pay-PRD-0260` — role → limits → pricing → ledger).

Without these:
- A misconfigured 100-pts reward rule firing on every event could mint
  unlimited points until someone notices in the audit log.
- A user could initiate a R 50,000,000 P2P transfer.
- The platform never collects fees, so the unit economics are wrong.

## 2. Data flow per control

```
P2P / top-up / redemption initiate:
  role check (Phase F.3)
  ─►  limits check (WAL-51)  ─►  pricing fee compute (WAL-52)
  ─►  ledger write (debit + credit + fee leg)
  ─►  audit_log + counters updated

Reward issuance (Kafka or admin):
  rule fires
  ─►  budget check (WAL-50)
  ─►  ledger write (reward_events + ledger entries)
  ─►  audit_log + budget consumption updated
```

Each control has its own table, its own admin CRUD surface, and lives in
its own service module so the rejection error is specific:
`limit_exceeded`, `min_amount_below_threshold`, `daily_count_exceeded`,
`daily_value_exceeded`, `budget_exceeded`, `pricing_config_missing`.

## 3. STRIDE — what's new

### 3.1 Budgets (WAL-50)

| ID | Category | Threat | Mitigation |
|---|---|---|---|
| G-B-S-1 | Spoofing | Caller forges `scope_id` in admin CRUD to bind a budget to a different tenant's rule | `tenant_id` on every budget row + on every admin call; rule existence check `WHERE tenant_id = principal.tenant_id` before write |
| G-B-T-1 | Tampering | Two concurrent reward fires both pass the budget check at 99% consumption → 198% spent | Budget consumption check + reward write happen inside a SELECT FOR UPDATE on the budget row. Tested via `test_budget_concurrent_fires_serialise` |
| G-B-R-1 | Repudiation | Admin disputes responsibility for a budget edit | Every budget create / update / delete writes an audit_log row with admin actor_id + before/after JSONB |
| G-B-I-1 | Info disclosure | Cross-tenant budget query reveals competitor's reward spend | Tenant filter on every read; `403` on cross-tenant lookups |
| G-B-D-1 | DoS | Adversary spams events knowing each consumes budget, exhausting it | Out of scope here — handled by Phase F.3 role check + Phase G rate limits (Phase G+1) |
| G-B-E-1 | Elevation | Operator with `finance-reviewer` (read-only) edits a budget | Only `platform-admin` mutates; route `dependencies=[require_admin_role("platform-admin")]` |
| G-B-A-1 | Alerting | Budget exhausts silently | Audit row written at 50% / 80% / 100% thresholds. Phase 2 → SMS/email alert |

### 3.2 Limits (WAL-51)

| ID | Category | Threat | Mitigation |
|---|---|---|---|
| G-L-T-1 | Tampering | User chains 100 small txns to bypass a single-txn max | `daily_count` + `daily_value` caps catch the aggregate |
| G-L-T-2 | Tampering | "Daily" cap reset attack — user trickles transactions around midnight UTC to consume two days' allowance in 4 hours | Window is "rolling 24h" from the txn timestamp, not calendar-day. Implemented as a `SUM(...) WHERE created_at > NOW() - INTERVAL '24h'` |
| G-L-T-3 | Tampering | Race condition — two concurrent same-user txns both see count=4 (under the cap of 5) and both write | Daily-count is recomputed inside the same DB tx as the ledger write, under `SELECT FOR UPDATE` on the sender wallet (already present from Phase B). The recompute runs AFTER the lock, so the second tx sees the first's writes |
| G-L-S-1 | Spoofing | Admin forges `tenant_id` on a limit config | Tenant on every limit row; admin path validates tenant against the principal |
| G-L-E-1 | Elevation | Admin gives one tenant a daily cap of R 10M to drain another tenant's pool | No pool sharing exists; limits are per-tenant + per-user. Confirmed in the data model |

### 3.3 Pricing (WAL-52)

| ID | Category | Threat | Mitigation |
|---|---|---|---|
| G-P-T-1 | Tampering | Caller mutates the displayed fee on the client to undercharge | Fee is computed server-side from `pricing_configs` at txn time, never trusted from the client. The response carries the fee for display only |
| G-P-T-2 | Tampering | Caller submits a zero-amount transaction to skip fees | `pricing_configs` allows configuring fee on zero — but most tenants will set zero-fee. The pricing check runs even on zero-amount txns (Pay-PRD-0420) |
| G-P-I-1 | Info disclosure | Pricing schedule leaks competitive intel via API | Pricing admin endpoints `platform-admin` only; user-facing fee preview returns just the computed fee, not the config |
| G-P-E-1 | Elevation | Operator disables fee collection mid-day | Audit row on every pricing config edit; finance-reviewer can read but only platform-admin can write |
| G-P-A-1 | Correctness | Pricing config missing for a `transaction_type` → silent zero fee | Service raises `PricingConfigMissing` 422 if no config exists; tenant has to explicitly set "zero fee" if that's the intent |

## 4. Data model

### `reward_budgets`

```sql
CREATE TABLE reward_budgets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    scope_type varchar(20) NOT NULL,      -- 'tenant' | 'rule'
    scope_id uuid,                         -- rule_id when scope_type='rule', else NULL
    currency char(3) NOT NULL,             -- 'PTS' for points budgets
    window_type varchar(20) NOT NULL,      -- 'rolling_24h' | 'rolling_7d' | 'calendar_month' | 'lifetime'
    cap_amount numeric(20,6) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active',  -- 'active' | 'paused'
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (scope_type IN ('tenant', 'rule')),
    CHECK (window_type IN ('rolling_24h', 'rolling_7d', 'calendar_month', 'lifetime')),
    CHECK (status IN ('active', 'paused')),
    -- Partial unique constraint per scope:
    --   per-tenant budget: one per (tenant, currency, window) when scope_id IS NULL
    --   per-rule budget: one per (tenant, rule, currency, window) when scope_id is set
);
CREATE UNIQUE INDEX uq_reward_budgets_tenant_scope
  ON reward_budgets (tenant_id, currency, window_type)
  WHERE scope_id IS NULL;
CREATE UNIQUE INDEX uq_reward_budgets_rule_scope
  ON reward_budgets (tenant_id, scope_id, currency, window_type)
  WHERE scope_id IS NOT NULL;
```

Consumption is computed live from `reward_events` (already
event-sourced). No separate counter table — keeps the invariant
"reward_events is the source of truth".

### `limit_configs`

```sql
CREATE TABLE limit_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    transaction_type varchar(50) NOT NULL,  -- 'p2p' | 'top_up' | 'redemption' | etc
    account_type varchar(30) NOT NULL,      -- 'financial_wallet' | 'points_account'
    currency char(3) NOT NULL,
    min_amount numeric(20,6),
    max_amount numeric(20,6),
    daily_count_cap integer,
    daily_value_cap numeric(20,6),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, transaction_type, account_type, currency)
);
```

Daily aggregates queried from `transactions` table directly (no counter
caching in Phase 1 — keep the source of truth single-rooted).

### `pricing_configs`

```sql
CREATE TABLE pricing_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    transaction_type varchar(50) NOT NULL,
    account_type varchar(30) NOT NULL,
    currency char(3) NOT NULL,
    fixed_fee numeric(20,6) NOT NULL DEFAULT 0,
    variable_fee_pct numeric(8,6) NOT NULL DEFAULT 0,  -- e.g. 0.025 = 2.5%
    fee_cap numeric(20,6),                              -- optional max on the variable component
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, transaction_type, account_type, currency)
);
```

Fee = `fixed_fee + min(variable_fee_pct * amount, fee_cap or +Inf)`.

A new system-owned account type collects fees: `system_fee_collected`,
one per (tenant, currency).

## 5. Orchestration update

`app/modules/payments/service.py::p2p_transfer` (and analogous in
`top_up`, `initiate_redemption`) becomes:

```
1. role check                                 (Phase F.3 — already in)
2. tenant + recipient identifier resolve      (Phase A)
3. self-transfer guard                        (Phase B)
4. wallet lookups + currency assertion        (Phase B)
5. acquire row-lock on sender wallet          (Phase B)
6. **limits check**                           (Phase G — NEW)
7. **pricing fee calculation**                (Phase G — NEW)
8. overdraft check (amount + fee)             (Phase B — augmented)
9. ledger write: [sender debit, recipient credit, fee debit, fee credit]
10. audit_log entry                           (Phase F.5)
```

Existing tests stay valid because step 6–7 are no-ops when no config
exists (graceful pass-through). The new tests assert behaviour when
config IS present.

## 6. Test scenarios

For each control: happy path · auth failure · tenant isolation ·
config absent (pass-through) · breach (rejection) · audit row written.

**Limits specific:**
- `test_p2p_below_min_amount_rejected`
- `test_p2p_above_max_amount_rejected`
- `test_p2p_daily_count_cap_enforced`
- `test_p2p_daily_value_cap_enforced_via_rolling_window`
- `test_no_limit_config_passes_through`

**Pricing specific:**
- `test_p2p_fixed_fee_added_as_ledger_leg`
- `test_p2p_variable_fee_capped_at_fee_cap`
- `test_zero_fee_config_still_writes_no_extra_leg`
- `test_overdraft_check_includes_fee`

**Budgets specific:**
- `test_reward_blocked_when_tenant_budget_exhausted`
- `test_reward_blocked_when_rule_budget_exhausted`
- `test_concurrent_fires_serialise_on_budget_lock` (race test)
- `test_50_80_100_pct_audit_thresholds_recorded`

## 7. Residual risks accepted for G.1

- **No real-time alerting.** Audit-log thresholds (50/80/100%) write
  rows but no SMS/email fan-out. Engagement integration (Epic 8) wires
  these to WebEngage.
- **Window arithmetic uses NOW() at the DB.** Clock skew between the
  app server and Postgres could move a txn out of its window by a few
  seconds. Acceptable in single-region; multi-region would need to pin
  to UTC at write time.
- **No retroactive budget adjustment.** Once consumed, lowering the cap
  doesn't refund prior issuances. Documented for operators.
- **Pricing config absent → 422, not silent zero.** Conservative
  default — operators must explicitly opt-in to zero fees per
  transaction_type.

## 8. Sign-off

- [x] STRIDE pass complete for all 3 controls
- [x] Race conditions documented + mitigation strategy
- [x] Data model finalised
- [x] Orchestration order locked
- Reviewed by: security agent (inline) on 2026-06-16
