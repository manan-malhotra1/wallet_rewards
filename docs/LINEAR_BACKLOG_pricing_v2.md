# Linear Backlog — Pricing v2 (Slab Fees · Agent Commissions · Taxes · Cash-In · Config Governance)

> **Purpose:** Importable per-initiative backlog, organised Epics × Stories (mirrors `docs/LINEAR_BACKLOG.md`).
> **Design spec:** `docs/superpowers/specs/2026-07-12-pricing-v2-design.md`
> **Source PRDs:** Product Module 6 (Pricing) + Module 5 (Limits); Pay-PRD-0260, 0420–0460. Extends the deferred commission/roll-up epic from `docs/superpowers/specs/2026-07-03-user-types-design.md` (Decision D4).
>
> **Status legend:** `Done` · `In Progress` · `Backlog` · `Deferred`. Everything below is **Backlog**.
>
> **Locked decisions:** commission = platform-funded pool, always additive (`DEBIT commission → CREDIT agent`); tax on BOTH fees and commissions, inclusive/exclusive configurable on three axes; commission v1 = acting agent only (hierarchy roll-up deferred); all pricing/limits/commission/tax config changes are maker-checker governed; services are fail-closed on config behind a per-tenant switch.
>
> **Epics build in order — 19 → 24.** Each story is one TDD'd, code-review + automation-testing-gated commit.

---

## Epic 19 — Charge Engine Foundation (Wallets · Slabs · Commission/Tax Configs) · **Backlog**

The config + ledger substrate for pricing v2: two new system wallets, amount-slab fees, and the commission/tax config models. Additive and back-compatible — no behaviour change to existing flows until the assembler (Epic 20) wires them in.

### Story 19.1 — `commission` + `taxes` system account types · Backlog

**Description:** Add two system account types (a platform-funded commission pool and a tax collector) plus their lazy get-or-create helpers, following the `airtime_merchant_holding` recipe.

**Acceptance criteria:**
- `ACCOUNT_TYPE_COMMISSION="commission"` and `ACCOUNT_TYPE_TAXES="taxes"` added to constants, the `ACCOUNT_TYPES` tuple, and the `ck_accounts_type` CHECK literal.
- Migration `0025` drops+recreates `ck_accounts_type` with the full 10-value list; downgrade filters the two new values back out; `alembic check` clean.
- `get_or_create_system_commission` / `get_or_create_system_taxes` mirror `get_or_create_system_fee_account` (keyword-only `(session, *, tenant_id, currency)`, `user_id IS NULL`, `IntegrityError`→rollback→refetch on the `uq_accounts_system_scoped` race).
- Balance guard is unchanged and skips both types (test: a large credit/debit to `commission`/`taxes` never trips overdraft or `max_balance`).

**Refs:** accounts.py; migration `0025` · **Labels:** pricing-v2; data; ledger · **Est:** 2

### Story 19.2 — Slab fees on `pricing_configs` (amount bands + resolution) · Backlog

**Description:** Add amount-band columns so fees can vary by transaction amount; make fee-config resolution amount-aware. Mirrors the limits module's `min_amount`/`max_amount`.

**Acceptance criteria:**
- Nullable `amount_from` / `amount_to` on `pricing_configs`; `uq_pricing_configs_scope` extended to include `amount_from`; `NULL` band = applies to all amounts (existing single-row configs keep working).
- `_find_pricing_config` filters `(amount_from IS NULL OR :amount >= amount_from) AND (amount_to IS NULL OR :amount < amount_to)`, ordered `user_type NULLS LAST, amount_from NULLS LAST LIMIT 1` — specific band beats NULL-band; typed row beats NULL-type.
- `calculate_fee` unchanged within the selected band (`fixed + min(pct·amount, cap)`).
- Tests: amount picks the right band; typed-band precedence; NULL-band back-compat; overlapping-band guard.

**Refs:** pricing.py; pricing/service.py:49-143 · **Labels:** pricing-v2; data; pricing · **Est:** 3

### Story 19.3 — `commission_configs` model + `calculate_commission` · Backlog

**Description:** Commission schedule (structural twin of pricing) + its computation. Resolves the acting agent's `user_type`.

**Acceptance criteria:**
- `commission_configs`: `(tenant, transaction_type, currency, user_type)` + amount bands → `fixed_commission`, `variable_commission_pct`, `commission_cap`; unique scope + CHECKs mirror `pricing_configs`.
- `calculate_commission(...)` clones `calculate_fee`; resolves `user_type` via `resolve_user_type`; missing config → `Decimal("0")` (no commission).
- Tests: fixed + variable + cap; typed vs default precedence; slab band selection; no-config → 0.

**Refs:** pricing/service.py (template) · **Labels:** pricing-v2; data; pricing · **Est:** 3

### Story 19.4 — `tax_configs` model + `calculate_tax` · Backlog

**Description:** Jurisdiction-wide tax rates + inclusive flags, and the tax computation on fee and commission.

**Acceptance criteria:**
- `tax_configs`: `(tenant, currency)` → `fee_tax_pct`, `commission_tax_pct`, `fee_tax_inclusive` (bool), `commission_tax_inclusive` (bool); unique on `(tenant, currency)`.
- `calculate_tax(...)` returns the fee-tax and commission-tax amounts given the base amounts + config; missing config → zero tax.
- Tests: percentage math; inclusive vs exclusive returns; no-config → 0.

**Labels:** pricing-v2; data; pricing · **Est:** 2

---

## Epic 20 — Charge Assembler & Ledger Integration · **Backlog**

The economic core: one shared function turns a principal + computed fee/commission/tax + the three inclusive/exclusive flags into a balanced ledger `entries` list, reused by every money path.

### Story 20.1 — `assemble_charges` (inclusive/exclusive matrix → balanced legs) · Backlog

**Description:** New `pricing/assembler.py`. Given base principal legs + `F/C/Tf/Tc` + `fee_inclusive` / `fee_tax_inclusive` / `commission_tax_inclusive`, append the fee/commission/tax legs and return the balanced `entries` + `(fee_amount, commission_amount, tax_amount)`.

**Acceptance criteria:**
- Produces `ΣCREDIT == ΣDEBIT` for **every** combination of the three flags (parametrized test matrix).
- Commission always additive from the `commission` wallet; tax always lands in `taxes`; fee in `system_fee_collected`.
- Matches the worked example in the design spec exactly (byte-for-byte legs).
- Reused by p2p + airtime (refactor their inline fee-leg block to call it) with no behaviour change when commission/tax are zero.

**Refs:** payments/service.py:298-343 (pattern); design spec §money-model · **Labels:** pricing-v2; pricing; ledger · **Est:** 5

### Story 20.2 — `Transaction.commission_amount` / `tax_amount` columns · Backlog

**Description:** Display-only sibling columns to `fee_amount`, threaded through `PostTransactionRequest`.

**Acceptance criteria:**
- `commission_amount`, `tax_amount` `Numeric(20,6)` default 0 on `transactions`; migration + downgrade; `alembic check` clean.
- `PostTransactionRequest` carries both; `post_transaction` writes them onto the row.
- Economics remain in the balanced legs (columns are for display); existing txns default to 0.

**Labels:** pricing-v2; data; ledger · **Est:** 2

### Story 20.3 — Commission cap-exemption on the balance guard · Backlog

**Description:** A commission CREDIT to an agent's `financial_wallet` is an earned payout and must not be blocked by `max_balance`. Generalise the `is_reversal` escape hatch into a `skip_receive_cap` flag.

**Acceptance criteria:**
- `PostTransactionRequest.skip_receive_cap` (or generalised reversal flag) exempts credit legs from the `max_balance` check but NOT the overdraft check.
- Cash-in commission credit lands even when the agent is at `max_balance`; a normal (non-exempt) credit over cap is still rejected.
- Guard tests extended (mirror `tests/ledger/test_balance_guard.py`).

**Refs:** ledger/service.py:298-312; invariant #11 · **Labels:** pricing-v2; ledger; security · **Est:** 2

---

## Epic 21 — Agent Cash-In Vertical · **Backlog**

First real consumer of the charge engine: an agent's e-float funds a customer's wallet; the agent earns a commission; fee + tax are collected.

### Story 21.1 — `cash_in` service catalog + agent role permission · Backlog

**Description:** Register the new service code and grant it to agents.

**Acceptance criteria:**
- `cash_in` added to the services catalog seed + a migration; default agent role gains the `cash_in` permission.
- `require_permission(agent, "cash_in")` gates the endpoint.

**Refs:** scripts/seed.py:157-179, :360 · **Labels:** pricing-v2; backend; data · **Est:** 2

### Story 21.2 — `cashin` module: agent-initiated deposit → customer wallet · Backlog

**Description:** New `modules/cashin/` (router + service). Order: role → limits → pricing(slab) → commission → tax → `assemble_charges` → overdraft on agent float → `post_transaction`. `initiated_by = agent`; credited `financial_wallet.user_id = customer`.

**Acceptance criteria:**
- Happy path: customer credited, agent commission paid from `commission` wallet, fee → `system_fee_collected`, taxes → `taxes`, all balanced.
- Auth failure (401), permission failure (403), tenant isolation (404), validation (422), Idempotency-Key replay returns the original, overdraft on the agent float → 409.
- Actor ≠ credited-owner handled (uses the existing recipient-facing guard branch).

**Refs:** ledger/service.py:298-312 · **Labels:** pricing-v2; backend; ledger · **Est:** 5

### Story 21.3 — Cash-in E2E + ledger-invariant tests + load profile · Backlog

**Description:** End-to-end proof + invariant coverage + a load profile.

**Acceptance criteria:**
- `test_ledger_sum_to_zero` stays green with 6–8-leg cash-in transactions.
- E2E: seed agent + customer, POST cash-in, assert all five balances (customer, agent, fee, commission, taxes) match a worked example.
- `scripts/load_test_p2p.py` gains a cash-in profile (or a sibling script).

**Labels:** pricing-v2; testing · **Est:** 3

---

## Epic 22 — Config Governance: Maker-Checker (Four-Eyes) · **Backlog**

Dual-control for all config changes (pricing, limits, wallet-limits, commission, tax): a change proposed by one admin only takes effect once a different admin approves; the checker can reject with comments and the maker revises and resubmits the same request.

### Story 22.1 — `config-approver` role + `SelfApprovalForbidden` · Backlog

**Description:** New Keycloak realm role and separation-of-duties exception.

**Acceptance criteria:**
- `config-approver` added to `REALM_ROLES` in `scripts/bootstrap_keycloak.py`; gated via the existing `require_admin_role("config-approver")`.
- `SelfApprovalForbidden` (409) exception added.

**Refs:** dependencies.py:64; bootstrap_keycloak.py:32 · **Labels:** pricing-v2; platform; auth · **Est:** 1

### Story 22.2 — `config_change_requests` + `config_change_reviews` models · Backlog

**Description:** A generic proposal table (all config types) + an append-only review/comment thread.

**Acceptance criteria:**
- `config_change_requests`: `config_type (pricing|limit|wallet_limit|commission|tax)`, `operation (create|delete)`, `payload` JSONB (editable across revisions), `target_config_id`, `status (PENDING|CHANGES_REQUESTED|APPLIED|WITHDRAWN)`, `maker_admin_id`, `checker_admin_id`, `revision`, timestamps.
- `config_change_reviews` (append-only): `request_id`, `actor_admin_id`, `actor_role (maker|checker)`, `action (submitted|changes_requested|revised|resubmitted|approved|withdrawn)`, `comment`, `created_at`.
- Migration + downgrade; tenant_id on both; `alembic check` clean.

**Labels:** pricing-v2; data · **Est:** 3

### Story 22.3 — Maker-checker endpoints + revise/resubmit loop · Backlog

**Description:** Propose → review → approve, with a reject-with-comments / revise-and-resubmit loop that preserves the request and its thread.

**Acceptance criteria:**
- `POST /config-requests` (maker, `platform-admin`) → PENDING, no config write, `submitted` review + audit.
- `POST /{id}/approve` (`config-approver`, `checker != maker` else 409) applies the create/delete in one transaction → APPLIED + audit.
- `POST /{id}/request-changes` (`config-approver`, `checker != maker`) with mandatory comment → CHANGES_REQUESTED (non-terminal).
- `PATCH /{id}` (original maker, only in CHANGES_REQUESTED) edits payload + bumps revision; `POST /{id}/resubmit` → PENDING. Same request id + full thread persist.
- `POST /{id}/withdraw` → WITHDRAWN. No config row exists until APPLIED. Tenant isolation. Full test loop: propose → request-changes → revise → resubmit → approve applies the revised config.

**Labels:** pricing-v2; backend · **Est:** 5

### Story 22.4 — Route config creation through approval; retire direct create/delete · Backlog

**Description:** Make four-eyes non-bypassable across pricing, limits, wallet-limits, commission, tax.

**Acceptance criteria:**
- The apply step of an approved request is the only path that writes a live config row.
- Existing direct pricing/limits create+delete endpoints removed (or restricted to non-prod) — decision recorded.
- Tests confirm a direct create attempt is rejected/absent.

**Labels:** pricing-v2; backend · **Est:** 3

---

## Epic 23 — Fail-Closed Service Gating · **Backlog**

A service may run only if BOTH pricing and limits resolve for the acting user's type; otherwise it fails. Rolled out behind a per-tenant switch so unconfigured tenants and tests aren't broken.

### Story 23.1 — Per-tenant flag + `require_pricing_and_limits` guard · Backlog

**Description:** The switch and the shared gate.

**Acceptance criteria:**
- `require_config_to_transact` boolean on `tenants`, default `false`; migration.
- `require_pricing_and_limits(session, *, tenant_id, service, account_type, currency, user_id)` resolves `user_type` and asserts both a pricing and a limit config resolve; else raises `ServiceNotConfigured` (422) naming service + user_type. No-op when the flag is off.

**Labels:** pricing-v2; backend; data · **Est:** 2

### Story 23.2 — Remove fail-open swallows; wire the gate into money paths · Backlog

**Description:** Flip the fail-open behaviour and enforce the gate.

**Acceptance criteria:**
- Remove `except PricingConfigMissing → Decimal("0")` in the money paths (payments, airtime); keep it only for the read-only `quote_fee` preview.
- Limits no-config early-`return` raises once the gate confirms a config; the gate is called at the top of each money path (after role).
- Tests: flag ON + missing pricing (or limits) for the user_type → `ServiceNotConfigured`; config present → succeeds; flag OFF preserves today's behaviour (regression safety).

**Refs:** payments/service.py:284, airtime/service.py:356, limits/service.py:214/430/517 · **Labels:** pricing-v2; backend · **Est:** 3

---

## Epic 24 — Pricing v2 Admin UI · **Backlog**

Admin surfaces for the new config, and the maker-checker review experience. (Frontend automation tests remain deferred per repo policy — manual smoke is the bar.)

### Story 24.1 — Pricing dialog: slab bands + `fee_inclusive` + per-band preview · Backlog

**Acceptance criteria:** create dialog gains `amount_from`/`amount_to` + `fee_inclusive`; the fee preview samples per band; validation for overlapping/adjacent bands.

**Refs:** admin-ui/app/(authenticated)/pricing/_components/create-pricing-dialog.tsx · **Labels:** pricing-v2; admin-ui · **Est:** 3

### Story 24.2 — Commission-config + tax-config admin screens · Backlog

**Acceptance criteria:** new pages/tables/actions cloning the pricing page pattern; create/list/delete (propose via the maker-checker flow).

**Labels:** pricing-v2; admin-ui · **Est:** 3

### Story 24.3 — Config-request review UI (maker submit + checker thread) · Backlog

**Acceptance criteria:** a config-requests queue; maker submit; checker approve / request-changes with comment; the revision thread rendered; role-gated actions (`config-approver` sees approve/request-changes).

**Labels:** pricing-v2; admin-ui · **Est:** 5

---

## Summary

| Epic | Title | Stories | Est |
|---|---|---|---|
| 19 | Charge Engine Foundation | 4 | 10 |
| 20 | Charge Assembler & Ledger Integration | 3 | 9 |
| 21 | Agent Cash-In Vertical | 3 | 10 |
| 22 | Config Governance (Maker-Checker) | 4 | 12 |
| 23 | Fail-Closed Service Gating | 2 | 5 |
| 24 | Pricing v2 Admin UI | 3 | 11 |
| **Total** | | **19** | **57** |

**Deferred (phase 2):** commission hierarchy roll-up across the `parent_user_id` chain (agent → super_agent). Schema already supports it.
