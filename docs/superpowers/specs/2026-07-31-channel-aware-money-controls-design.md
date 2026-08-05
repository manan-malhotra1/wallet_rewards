# Channel-Aware Money-Movement Controls — Design & Implementation Plan

**Date:** 2026-07-31
**Status:** DECISIONS LOCKED — ready to convert to a task-by-task implementation plan (no code yet)
**Author:** Manan (with Claude)

---

## 1. Problem & threat model

Two abuse scenarios for money-moving services (`fund`, `withdraw`, and by extension `p2p`, `cashin`, `cashout`):

1. **Rogue administrator** — a legitimate admin acting maliciously from the Admin UI (web channel).
2. **Leaked / rogue API key** — an HMAC API key that has been publicly shared or stolen, driving the external API channel.

The two channels reach money movement through **different code paths** and must be contained by **different mechanisms**. This plan makes that split explicit and closes the gaps.

---

## 2. What exists today (verify these claims)

| Area | Current behavior | Evidence |
|---|---|---|
| Admin fund/withdraw | Do **not** execute — they `propose_money_operation(...)` (maker-checker). Nothing hits the ledger until distinct approvals land. | `treasury/router.py:90,121` (`post_fund_user`, `post_withdraw_from_user`) |
| Self-approval | **Blocked** — approver ≠ maker enforced. | `money_operations/service.py:320,389` (`SelfApprovalForbidden`) |
| Distinct approvals | Counted; executes when `required_approvals` distinct approvals land. | `money_operations/service.py:118,337` (`distinct_approver_ids`) |
| Approval count | **Fixed** per `(tenant, operation)`, `required_approvals ∈ {1,2}`. **NOT** amount- or count-aware. | `money_operations/service.py:213` (`_resolve_required_approvals`), `models/money_operations.py` `ck_..._required_approvals IN (1,2)` |
| API fund/withdraw | **Execute immediately** — `require_pricing_and_limits` → `check_limits` → `fund()`. **No maker-checker.** | `external/router.py:88,112`; `external/service.py:247` (`external_fund`) |
| Per-service limits (`LimitConfig`) | Enforced on the **API/consumer** paths (`check_limits`), **not** on the admin fund/withdraw path. Aggregates by `initiated_by`. | `limits/service.py:193` (`check_limits`), `:157` (`_aggregate_user_txns`) |
| Transaction actor | `transactions.initiated_by` = the **affected consumer** (wallet owner). There is **no** field for the actual initiator (admin / API key) or the channel. | `models/ledger.py` (Transaction), `treasury/service.py:413` sets `initiated_by=user_id` |

**Conclusion of the audit:** the admin channel is already behind maker-checker (contains a single rogue admin), but the approval count is static, and the API channel has **no** approval gate and **no** per-key velocity control. The transaction record cannot today distinguish *who initiated* an operation from *whose wallet was affected*.

---

## 3. The design — two-channel containment

```
                        money-moving service (fund / withdraw / p2p / cashin / cashout)
                                          │
                 ┌────────────────────────┴────────────────────────┐
        ADMIN channel (web / Keycloak JWT)              API channel (HMAC key)
                 │                                                  │
        maker-checker + DYNAMIC approval escalation        NO maker-checker
                 │                                                  │
     required_approvals = max(Config A, Config B)         HARD velocity limits
        floor 1, ceiling 3                                 per (service, channel, key)
                                                           count/value · daily/weekly/monthly
                                                           breach → reject before ledger
```

### 3.0 Shared prerequisite — record the *actor* on every transaction

Split the two roles the transaction currently conflates:

- **Subject** = affected wallet owner → keep `transactions.initiated_by` (unchanged; all existing per-consumer limits keep working).
- **Actor** = who/what triggered it → **new columns** on `transactions`:
  - `channel` — `web` | `api` | `mobile` | `ussd` | `system`
  - `initiator_type` — `admin` | `api_key` | `user` | `system`
  - `initiator_id` — Keycloak admin id **or** API key id (`key_id`, never the secret) **or** user id **or** `system`

Both `channel` and `initiator_id` are derivable at request time from how the request authenticated (JWT admin principal vs `ApiKeyPrincipal`). This single data change unlocks **both** Config A (count by initiator) and the API velocity limits (count by key).

### 3.1 ADMIN channel — dynamic approval escalation

Approval **#1 is always mandatory** (existing four-eyes floor). **#2 and #3** are added dynamically at propose time by two **independent, per-service** configs. The final requirement is the **stricter (max)** of the two, clamped to `[1, 3]`.

**Config A — count-based escalation** (per `transaction_type`):
Escalates on how many transactions of this service the **same initiator** has executed.
- Window: **daily only** (decided) — a rolling 24-hour window.
- Bands → required approvals. Example (`fund`):

  | Initiator's APPLIED count (last 24h) | Approvals |
  |---|---|
  | 1st–3rd | 1 |
  | 4th–6th | 2 |
  | 7th+ | 3 |

- "Count" = **APPLIED** (executed) money-operations of this type by this `initiator_id` in the rolling 24h window. **Pending proposals do NOT count** (decided) — an actor can't inflate their own requirement by stacking un-approved requests.

**Config B — amount-based escalation** (per `transaction_type`, **per currency**):
Escalates on the **amount of the current transaction**. Currency chosen from the tenant's actual currencies (dropdown — never cross-currency). Example (`withdraw`, ZAR):

  | Amount | Approvals |
  |---|---|
  | any | 1 |
  | > 50,000 | 2 |
  | > 500,000 | 3 |

**Resolution at propose time:**
```
required_approvals = clamp(
    max(
        count_tier(initiator_id, transaction_type, window),   # Config A, 0 if unconfigured
        amount_tier(transaction_type, currency, amount),      # Config B, 0 if unconfigured
        1                                                     # mandatory floor
    ),
    1, 3
)
```
This replaces the static `_resolve_required_approvals(tenant, operation)`.

### 3.2 API channel — hard velocity limits (no approval)

The API path keeps executing immediately (no maker-checker — **confirmed decision**), but gains a **hard velocity cap** keyed on the **specific API key** (decided — per-key only, no channel-type aggregate):

- Scope: `(tenant, transaction_type, channel = api, initiator_id = key_id)`. **Each key has its own budget** — a leaked key is contained on its own, and one busy key never consumes another's allowance.
- Axes: **count** and **value**, rolling **daily / weekly / monthly** (x / y / z).
- On breach → **reject before any ledger write** (409/422), same fail-closed posture as existing limits.
- Slots into the `check_limits` path the API already calls — extended to resolve a per-key config and aggregate by `initiator_id = key_id` (over the new transaction actor field).

This is the containment for a leaked key: that specific key can move at most x/day, y/week, z/month regardless of how many consumers it targets.

### 3.3 Channel allow-list (authorization — in scope, decided)

Independent of *how much* (velocity) and *how many approvers* (escalation), the allow-list controls **whether a channel may initiate a service at all**. It is a policy matrix `(tenant, transaction_type) → allowed channels`.

- Example: `p2p` allowed only from `mobile` / `ussd`; `fund` / `withdraw` allowed from `web` / `api`. A request whose resolved `channel` is not in the allow-list is **rejected before any ledger write** (403/422), on every money path.
- This is binary authorization, not a cap — it belongs with the **service definition** (services module / catalog), resolved from the request's channel (JWT → `web`, `ApiKeyPrincipal` → `api`, etc.).
- Default when unconfigured: **allow all channels** (no behavioral change until a policy is set), to avoid breaking existing flows — a tenant opts in per service.

---

## 4. Schema changes

1. **`transactions`** — add `channel`, `initiator_type`, `initiator_id` (all with a CHECK on allowed values; `initiator_id` a plain string id). Backfill existing rows as `channel='system'`, `initiator_type='system'` (rolling windows are only meaningful going forward).
2. **`approval_policies`** — this static table is superseded by dynamic resolution. Two new config tables (or extend it):
   - `approval_count_tiers` — `(tenant_id, transaction_type, min_count, required_approvals)` — Config A. Window is **daily** (fixed) so no window column.
   - `approval_amount_tiers` — `(tenant_id, transaction_type, currency, min_amount, required_approvals)` — Config B.
   Both `required_approvals ∈ {1,2,3}` (relax the current `IN (1,2)` CHECK to `IN (1,2,3)` — **ceiling raised to 3, confirmed**).
3. **`channel_limit_configs`** (sibling of `limit_configs`) — the per-key API velocity caps: `(tenant_id, transaction_type, channel, initiator_id, daily/weekly/monthly count+value caps)`. Keyed to a **specific `initiator_id` (key_id)**.
4. **`service_channel_policies`** (services module) — the allow-list: `(tenant_id, transaction_type, allowed_channels)`. Absent row = all channels allowed.

All migrations via Alembic (invariant 3). All new tables carry `tenant_id` (invariant 7).

---

## 5. Enforcement points

| Path | Guard added |
|---|---|
| **Every** money path (a shared pre-ledger guard) | **Channel allow-list** — reject if the request's `channel` is not allowed for this `transaction_type`. |
| Admin `propose_money_operation` (fund/withdraw) | Compute `required_approvals` dynamically from Config A + Config B (max, clamp 1–3) at propose time. |
| API `external_fund` / `external_withdraw` | Extend `check_limits` with the **per-key** channel velocity cap; reject before ledger on breach. |
| `post_transaction` | Persist `channel` / `initiator_type` / `initiator_id` (passed down from the router via the auth principal). No change to the balance-guard invariant. |

The existing choke-point balance guard (overdraft floor / `max_balance` ceiling, invariant 11) and per-consumer wallet caps are untouched.

---

## 6. Admin UI

- **Approval configuration** screen, per service: two sub-forms — a **count-tier ladder** (Config A) and an **amount-tier ladder** with a **currency dropdown** (Config B), each mapping bands → 1/2/3 approvals.
- **Channel velocity limits** screen: per service + channel + (optional) specific API key, count/value caps for daily/weekly/monthly.
- Both follow the existing config maker-checker pattern where applicable.

---

## 7. Phasing

**Target services: `fund` and `withdraw` are the must** (admin-triggered — the rogue-admin/leaked-key surface). Build the machinery generically so `p2p` / `cashin` / `cashout` can be enabled later by config, but the acceptance bar for this plan is fund + withdraw.

1. **Data foundation** — add `channel` / `initiator_type` / `initiator_id` to `transactions`; thread them from both routers (JWT → admin/web, `ApiKeyPrincipal` → api) through `post_transaction`. (Prerequisite for everything.)
2. **Channel allow-list** — shared pre-ledger guard + `service_channel_policies`; reject disallowed channel. (Cheap, high-value, unblocks nothing else.)
3. **API velocity limits** — per-key channel caps in `check_limits`; the leaked-key containment. Tests: breach rejects, isolation per key.
4. **Config B (amount-based approval)** — amount-tier resolution in the propose path; raise ceiling to 3.
5. **Config A (count-based approval)** — daily rolling count-tier resolution using the new `initiator_id`, APPLIED-only.
6. **Admin UI** — the approval-config screens (count ladder + amount ladder w/ currency dropdown), the per-key velocity screen, and the allow-list matrix.

Each phase ships with backend tests per the coding guidelines (happy path, auth, tenant isolation, boundary conditions on each tier/cap). `fund` + `withdraw` covered end-to-end before the plan is considered done.

---

## 8. Decisions (resolved)

- **Q1 — Config A window:** **daily only** (rolling 24h).
- **Q2 — API velocity granularity:** **per specific key** (`initiator_id = key_id`) only — no channel-type aggregate.
- **Q3 — Config A counting:** **APPLIED transactions only** — pending proposals do not count.
- **Q4 — Rollout scope:** **`fund` + `withdraw` are the must** (admin-triggered); machinery built generically so other services can be enabled later by config.
- **Q5 — Channel allow-list:** **in scope** — included as Phase 2 (§3.3, §7).

---

## 9. Explicitly out of scope (this plan)

- Routing the API channel through maker-checker (decided against — API is controlled by per-key velocity limits).
- Changing the per-consumer wallet limits or the choke-point balance guard.
- Approval requirements above 3.
- Enabling Config A/B, velocity, or allow-list for `p2p` / `cashin` / `cashout` beyond leaving the machinery generic (fund + withdraw are the acceptance target).
