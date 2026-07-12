# Pricing v2 — Slab Fees · Agent Commissions · Taxes · Cash-In

**Date:** 2026-07-12 · **Status:** Approved (Manan, 2026-07-12) · **Tracking:** `docs/LINEAR_BACKLOG_pricing_v2.md` (Epics 19–24)
**Related:** [Product PRD](../../02-prd.md) Module 6 (Pricing) / Module 5 (Limits); [user-types design](2026-07-03-user-types-design.md) — this is the commission/roll-up epic deferred by Decision D4.

## Context

Today pricing is a single flat schedule: `PricingConfig` = `fixed_fee + min(variable_fee_pct × amount, fee_cap)`, keyed on `(tenant, transaction_type, account_type, currency, user_type)` — **no amount tiers, no commissions, no tax, and no agent-acts-for-customer flow** (all confirmed greenfield — zero hits for `cash_in`/`commission`/`tax`/`slab` in `app/`). The user-types design doc **explicitly deferred "commission calculation and hierarchy roll-ups" to a later epic** (Decision D4). This is that epic.

Goal: extend pricing with (a) **amount-slab fees**, (b) **agent commissions** paid from a platform-funded `commission` system wallet to an agent who performs a service for a customer, and (c) **taxes** on fees and commissions collected into a `taxes` system wallet — with inclusive/exclusive configurable. First real consumer: a net-new **agent cash-in** flow (agent's e-float funds a customer's wallet; agent earns commission).

> **NOTE — this is a research/design plan only; no code is to be written yet.** Worked ledger examples below are the contract to validate before building.

## Decisions locked (from you)

1. **Commission = platform-funded pool.** Always *additive* (extra), never carved from the fee: `DEBIT commission_wallet → CREDIT agent_wallet`. The operator tops the pool up; it can run negative-in-effect (system account, unguarded).
2. **Tax on BOTH fees and commissions**, rate configurable per each; collected in the `taxes` wallet.
3. **Inclusive/exclusive is configurable** (both supported) on three independent axes (below). Commission itself is always additive.
4. **Scope = engine + cash-in flow.**
5. **v1 = commission to the acting agent only.** Hierarchy roll-up (agent → `super_agent` via `parent_user_id`) deferred to a follow-on, consistent with D4.
6. **All config changes are maker-checker governed** (four-eyes): pricing, limits, commission, and tax configs are *proposed* by one admin and only take effect once a *different* admin holding a new `config-approver` role approves. The checker can **reject with comments**, and the maker **revises and resubmits the same request** (comment thread preserved, no starting over). (New requirement.)
7. **Services are fail-closed on config.** A service runs only if BOTH pricing and limits resolve for the acting user's type; otherwise it fails. Rolled out behind a per-tenant switch so unconfigured tenants aren't broken. (New requirement.)

## The money model — 4 axes + worked example

Terms: `A`=amount, `F`=fee (slab pricing), `C`=commission, `Tf`=tax on fee, `Tc`=tax on commission. Actor = agent (`Transaction.initiated_by`); beneficiary = credited customer wallet.

| Axis | Flag | Exclusive | Inclusive |
|---|---|---|---|
| Fee vs amount | `fee_inclusive` | payer pays `A+F`; customer gets `A` | payer pays `A`; customer gets `A−F` |
| Tax vs fee | `fee_tax_inclusive` | fee-side charge = `F+Tf`; platform keeps `F`, taxes get `Tf` | fee `F` already contains tax; platform keeps `F−Tf`, taxes get `Tf` |
| Tax vs commission | `commission_tax_inclusive` | commission wallet pays `C+Tc`; agent gets `C`, taxes get `Tc` | commission wallet pays `C`; agent nets `C−Tc`, taxes get `Tc` |

Commission is always: `DEBIT commission_wallet → CREDIT agent` (± its tax split per axis 3).

**Worked cash-in** — `A=100`, `F=2`, `Tf=0.30`, `C=1`, `Tc=0.15`; config = fee **inclusive** of amount, fee-tax **exclusive**, commission-tax **inclusive**. Every economic pair balances, so `ΣDEBIT == ΣCREDIT` across the whole `entries` list (which is all `_assert_balanced` requires):

```
Principal + fee (fee inclusive: customer receives A−F; fee-tax exclusive adds Tf on top, borne by customer via a smaller credit):
  DEBIT  agent_float          100.00
  CREDIT customer_wallet       97.70      # A − F − Tf  (fee inclusive of amount, tax on top)
  CREDIT system_fee_collected   2.00      # F
  CREDIT taxes                  0.30      # Tf
Commission (additive from pool; commission-tax inclusive → agent nets C−Tc):
  DEBIT  commission_wallet      1.00      # C
  CREDIT agent_wallet           0.85      # C − Tc
  CREDIT taxes                  0.15      # Tc
```
Debits `101.00` == credits `97.70+2.00+0.30+0.85+0.15 = 101.00`. ✓ (Flipping a flag only moves which leg an amount lands on — the assembler, below, owns that.)

## Design

### 1. Two new system wallets — `commission`, `taxes`
Follow the **exact recipe** the exploration confirmed (mirrors `airtime_merchant_holding`, rev `0015`):
- `backend/app/shared/models/accounts.py`: add `ACCOUNT_TYPE_COMMISSION="commission"`, `ACCOUNT_TYPE_TAXES="taxes"` to the constants (`:29-49`), the `ACCOUNT_TYPES` tuple (`:51-60`), and the hand-written `ck_accounts_type` literal (`:76-88`).
- `backend/app/shared/models/__init__.py`: add to imports + `__all__`.
- New migration `backend/alembic/versions/20260711_0025_accounts_commission_and_taxes.py` (`revision="0025"`, `down_revision="0024"`) — copy the `0015` body; `ALLOWED_TYPES` = full 10-value list.
- Two `get_or_create_*` helpers cloning `get_or_create_system_fee_account` (`backend/app/modules/pricing/service.py:207-255`), keyword-only `(session, *, tenant_id, currency)`, filtering `user_id.is_(None)`, relying on `uq_accounts_system_scoped` for the race.
- **No balance-guard change**: `_enforce_balance_guard` (`ledger/service.py:277-283`) only guards `financial_wallet` legs, so these system wallets are skipped (they may run "negative"/unbounded by design).

### 2. Slab fees — extend `pricing_configs`
Add nullable `amount_from` / `amount_to` columns (mirror the limits module's `min_amount`/`max_amount` prior art). Multiple rows per existing scope, each a band `[amount_from, amount_to)`; `NULL` band = applies to all amounts (back-compat with today's single-row configs). Extend `uq_pricing_configs_scope` to include `amount_from`.
- Change **row selection** in `_find_pricing_config` (`pricing/service.py:49-79`) to filter by amount: `(amount_from IS NULL OR :amount >= amount_from) AND (amount_to IS NULL OR :amount < amount_to)`, `ORDER BY user_type NULLS LAST, amount_from NULLS LAST LIMIT 1` — so a specific band beats the NULL-band default and a typed row beats the NULL-type default. `calculate_fee` (`:87-143`) is otherwise unchanged (still `fixed + min(pct·A, cap)` within the selected band).

### 3. `commission_configs` (new table)
Structural twin of `pricing_configs`: `(tenant, transaction_type, currency, user_type)` + amount bands → `fixed_commission`, `variable_commission_pct`, `commission_cap`. New `calculate_commission(...)` service (clone `calculate_fee`). Resolves the **acting agent's** `user_type` via `resolve_user_type` (`shared/utils/user_types.py`). Missing config → `Decimal("0")` (no commission), mirroring the `PricingConfigMissing`-swallow pattern.

### 4. `tax_configs` (new table) — **recommended separate table**
Keyed `(tenant, currency)` (extensible to per-service later) → `fee_tax_pct`, `commission_tax_pct`, `fee_tax_inclusive` (bool), `commission_tax_inclusive` (bool). Rationale: VAT is jurisdiction-wide — co-locating the rate on every pricing/commission row would denormalize it. New `calculate_tax(...)` service. (The `fee_inclusive` axis-1 flag lives on `pricing_configs`.)

### 5. Charge assembler (new shared service) — the heart
One function, e.g. `assemble_charges(...)` in a new `backend/app/modules/pricing/assembler.py`, that takes the base principal legs + computed `F/C/Tf/Tc` + the three flags and **returns the fully-balanced `entries` list plus `(fee_amount, commission_amount, tax_amount)`**. This centralizes the inclusive/exclusive matrix so `p2p`, `airtime`, and `cash_in` reuse identical, tested logic (satisfies the no-duplication guideline). Clone the leg-append shape from `payments/service.py:298-343`.

### 6. `Transaction` display columns
Add `commission_amount`, `tax_amount` (Numeric(20,6), default 0) beside the existing `fee_amount` (`ledger/service.py:157`, `models/ledger.py:98`); thread through `PostTransactionRequest` (`ledger/service.py:94`). Display-only — the economics already live in the balanced legs.

### 7. Balance-guard interaction — one decision to confirm
The commission **CREDIT lands on the agent's `financial_wallet`**, so invariant #11 will cap-check it. **Recommendation: make commission credits cap-exempt** (earned payout, not user-driven inflow) by generalizing the existing `is_reversal` escape hatch (`ledger/service.py:298`, `models/ledger.py:82-85`) into a broader `skip_receive_cap` flag on `PostTransactionRequest`. (Alternative: let commissions be capped — simpler but can block a legitimate payout.)

### 8. Cash-in flow (net-new)
- New service code `cash_in`: add to the services catalog seed (`scripts/seed.py:157-179`) + default agent role permission (`seed.py:360`) + migration.
- New module `backend/app/modules/cashin/` (router + service), agent-authenticated. Order of operations (Pay-PRD-0260 shape): role (`require_permission(agent,"cash_in")`) → limits → pricing (slab `F`) → commission (`C`) → tax (`Tf`,`Tc`) → `assemble_charges` → overdraft on the agent float → `post_transaction`. `initiated_by = agent`; credited `financial_wallet.user_id = customer` (the ledger already treats actor ≠ credited-owner as first-class — `ledger/service.py:298-312`). Idempotency-Key required.

### 9. Admin UI
- Extend the pricing create dialog (`admin-ui/app/(authenticated)/pricing/_components/create-pricing-dialog.tsx`) with `amount_from`/`amount_to` and the `fee_inclusive` flag; the preview (`:110-117`) should sample per band.
- New commission-config and tax-config admin screens (clone the pricing page/table/actions pattern). All create/list/delete only (no update path exists today).

### 10. Config governance — maker-checker (four-eyes)

Today any single `platform-admin` creates/deletes pricing & limits configs unilaterally (`require_admin_role("platform-admin")` on every pricing/limits endpoint — `dependencies.py:64`; create/delete only, no UPDATE, no approval). Add dual-control so a change proposed by one admin only lands once a **different** admin approves it. Applies to pricing, limits, wallet-limits, and the new commission/tax configs.

- **New Keycloak role `config-approver`** — add to `REALM_ROLES` (`scripts/bootstrap_keycloak.py:32`, alongside `platform-admin`/`finance-reviewer`/`support-agent`). Enforced with the *existing* `require_admin_role("config-approver")` — no new mechanism. (Precedent: reconciliation's `_require_finance_or_admin` already role-differentiates read vs state-change.)
- **New generic `config_change_requests` table** — one workflow for every config type: `id, tenant_id, config_type (pricing|limit|wallet_limit|commission|tax), operation (create|delete), payload JSONB (the proposed row — editable in place by the maker across revisions), target_config_id (nullable, for delete), status (PENDING|CHANGES_REQUESTED|APPLIED|WITHDRAWN), maker_admin_id, checker_admin_id, revision (int), created_at, updated_at`. Plus an **append-only `config_change_reviews` child table** for the back-and-forth thread: `id, request_id, actor_admin_id, actor_role (maker|checker), action (submitted|changes_requested|revised|resubmitted|approved|withdrawn), comment, created_at`. Preferred over per-row status columns: uniform, "active config == what's in the config tables" stays true for enforcement/readers, and the same request row + its thread persist across the whole loop (no starting over).
- **Flow (revise-and-resubmit loop):**
  - Maker `POST /api/v1/config-requests` (gated `platform-admin`) → `PENDING`, **no config write yet**; `submitted` review row + audit `config_request.proposed`.
  - Checker `POST /{id}/approve` (gated `config-approver`, asserts **`checker != maker`** → new `SelfApprovalForbidden` 409) applies the create/delete to the real config table in one transaction → `APPLIED`; `approved` review row + audit + the underlying `pricing_config.created`/etc.
  - Checker `POST /{id}/request-changes` (gated `config-approver`, `checker != maker`) with a **mandatory comment** → `CHANGES_REQUESTED`; `changes_requested` review row. **Not terminal** — returns to the maker.
  - Maker `PATCH /{id}` (original maker only, only while `CHANGES_REQUESTED`) edits `payload` in place (bumps `revision`), then `POST /{id}/resubmit` → back to `PENDING`; `revised` + `resubmitted` review rows. Loop until approved.
  - Maker `POST /{id}/withdraw` → `WITHDRAWN` (terminal) to abandon. (Optional hard terminal `REJECTED` by the checker — confirm on review.)
- **Make four-eyes non-bypassable:** the existing direct pricing/limits create+delete endpoints are removed (or, in non-prod only, retained) so the *only* path to a live config is an approved request. (Confirm on review.)
- Second-actor precedent to mirror: airtime `resolve_recharge(admin)` + reconciliation manual-resolve — but the maker≠checker constraint is net-new.
- *Verification:* propose→approve applies the config; **request-changes (with comment) → maker revises payload → resubmit → approve applies the *revised* config under the same request id with the full review thread intact**; approve/request-changes by the maker → 409; approve without `config-approver` → 403; revise by a non-maker or when not in `CHANGES_REQUESTED` → 409/403; no config row exists until `APPLIED`; audit + review rows for every transition; tenant isolation on requests.

### 11. Fail-closed service gating

A service currently runs even when unconfigured — pricing swallows `PricingConfigMissing → Decimal("0")` (`payments/service.py:284`, `airtime/service.py:356`, `pricing/service.py:198`) and limits no-op when absent (`limits/service.py:214-215, 430-431, 517-518` — "intentional pass-through"). So an agent/merchant/consumer can transact fee-free with no limits when config is missing.

- **New shared gate** `require_pricing_and_limits(session, *, tenant_id, service, account_type, currency, user_id)` (in `pricing` or a small `config_guard` util): resolves the acting `user_type` (`resolve_user_type`) and asserts BOTH a pricing config AND a limit config resolve (typed row or NULL-default) for the scope; else raise new `ServiceNotConfigured` (422) naming the service + user_type. Called at the top of each money path (after the role check).
- **Stop the swallows** in the money paths (remove the `except PricingConfigMissing → 0` blocks; let `calculate_fee` propagate). Keep the swallow only in `quote_fee` for read-only preview, or have preview report "not configured".
- **Limits:** flip the no-config early-`return` to raise once the gate is on (the gate having already confirmed a config resolves).
- **Rollout safety:** gate behind a **per-tenant `require_config_to_transact` flag (default OFF)**, flipped ON once a tenant's pricing+limits are populated for its active user types — same fail-open-until-configured tension as M-01, avoiding a global break. Seed covers only `p2p, airtime_recharge, redemption, top_up` at the default level today (`scripts/seed.py:605-793`), so a global flip would break any (service, user_type) lacking a row.
- Interaction: `cash_in` (§8) is subject to this gate; commission/tax being "configured" is part of the pricing side once present.
- *Verification:* with the flag ON, a service with no pricing (or no limits) for the user_type → `ServiceNotConfigured`; with config present → succeeds; flag OFF preserves today's behavior (regression safety for existing tenants/tests).

## Critical files

- **Reuse as templates:** `backend/app/modules/pricing/service.py:207-255` (system-account helper), `:49-143` (config resolution + fee math), `backend/app/modules/payments/service.py:298-343` (fee-leg pattern), `backend/alembic/versions/20260619_0015_airtime_merchant_holding.py` (account-type migration), `backend/app/modules/limits/schemas.py:56-58` (amount-band prior art).
- **Extend:** `shared/models/{accounts,pricing,ledger}.py`, `modules/pricing/{service,schemas,router}.py`, `modules/ledger/service.py` (new `PostTransactionRequest` fields + optional cap-exempt flag).
- **New:** `modules/pricing/assembler.py`, `modules/commissions/` + `modules/taxes/` (or fold configs into `pricing`), `modules/cashin/`, `modules/config_requests/` (maker-checker) + a `require_pricing_and_limits` guard util, models for `commission_configs`/`tax_configs`/`config_change_requests`, migrations `0025`+ (accounts, pricing slabs, commission/tax tables, config_change_requests, `cash_in` service, per-tenant `require_config_to_transact` flag on `tenants`).
- **Also touch:** `scripts/bootstrap_keycloak.py:32` (add `config-approver` realm role); the existing pricing/limits routers (remove or restrict the direct create/delete now that changes go via approved requests).

## Verification

- **Unit:** slab selection (amount picks the right band; typed-band beats default; NULL-band back-compat); `calculate_commission`/`calculate_tax`; assembler produces balanced legs for **every** inclusive/exclusive combination (parametrized).
- **Ledger invariants:** `tests/invariants/test_ledger_sum_to_zero` stays green with 6–8-leg cash-in transactions; guard **skips** `commission`/`taxes` wallets (mirror `tests/ledger/test_balance_guard.py`); commission-credit cap-exemption behaves as decided.
- **Endpoint (cash_in):** happy path (customer credited, agent commission paid, fee+tax to system wallets, all balanced), auth/permission failures, tenant isolation, idempotency replay, overdraft on agent float.
- **E2E:** run `make dev`, seed an agent + customer, POST `/api/v1/cashin`, assert the four balances (customer, agent, `system_fee_collected`, `commission`, `taxes`) match a worked example; extend `scripts/load_test_p2p.py` for a cash-in load profile.
- Gate: `make check` (ruff + mypy + `alembic check`) + full money-path sweep.

## Phased / open

- **Phase 2:** commission hierarchy roll-up (split across `parent_user_id` chain) — schema already supports it (`users.parent_user_id`, `PARENT_TYPE_BY_CHILD`).
- **Confirm on review:** the inclusive/exclusive worked examples (§money model); commission cap-exemption (§7); separate `tax_configs` vs co-located tax fields (§4); whether the direct pricing/limits create-delete endpoints are removed entirely once maker-checker lands (§10); and whether fail-closed requires a *type-specific* config or accepts the NULL-default row, plus the per-tenant rollout switch (§11).
