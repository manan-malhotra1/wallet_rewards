# 07 — Redemption & Reconciliation

> **Purpose:** how a user spends points on an external reward (Module 11) and how stuck redemptions are swept,
> escalated, and manually resolved without ever violating the append-only ledger (Module 12).
> **Related:** [05 — Rewards, Rules & Referral](05-rewards-rules-and-referral.md) (where points are earned),
> [02 — Ledger, Accounts & Money Movement](02-ledger-accounts-and-money-movement.md) (`post_transaction`, the
> balance guard), [03 — Money Controls](03-money-controls-pricing-limits-roles-step-up.md) (role/step-up gates).
> **README anchor:** [§5 The money core](README.md#5-the-money-core--one-choke-point-one-guard).
> **PRD modules:** 11 (Redemption, Pay-PRD-0660–0740), 12 (Reconciliation, Pay-PRD-0750–0800).

---

## 1. Overview

There are two redemption modes: the **external** flow below (points → third-party benefit, as built), and an
**internal** flow (points → fiat credited to the user's own wallet at an admin-configured rate) which is
**specced in §6 and not yet built**.

The external flow converts points into an external benefit (voucher, airtime, etc.) fulfilled by a third-party
provider. Because fulfilment is external and asynchronous, the redemption row is a **state machine**:
`PENDING → COMPLETED | FAILED | REVERSED`. Points are reserved on initiation and only truly spent on success; a
failure reverses the reservation. All money movement funnels through the ledger `post_transaction` choke point
(txn type `redemption`), so the append-only and idempotency invariants hold here as everywhere.

The one structural difference from other money paths: **redemption owns its own `points_account` FOR UPDATE
lock**, separate from the wallet balance guard. The wallet guard only guards `financial_wallet` and
`system_cash_inflow` — points accounts are *skipped* by it (doc 02). To prevent a points overdraft under
concurrency, redemption locks the user's points account itself at the choke point.

```mermaid
stateDiagram-v2
    [*] --> PENDING: initiate_redemption<br/>(reserve points under points_account lock)
    PENDING --> COMPLETED: confirm_redemption / callback success
    PENDING --> FAILED: fail_redemption / callback failure
    PENDING --> REVERSED: manual resolve (REVERSED)
    FAILED --> REVERSED: reversal legs restore points
    PENDING --> MANUAL_REVIEW: sweep_pending (stale)
    MANUAL_REVIEW --> COMPLETED: manually_resolve(COMPLETED)
    MANUAL_REVIEW --> REVERSED: manually_resolve(REVERSED)
    COMPLETED --> [*]
    REVERSED --> [*]
```

---

## 2. Redemption lifecycle (`modules/redemption/service.py`)

### 2.1 Provider registration

`register_provider` (`:115`, `POST /redemption/providers`, `platform-admin`) persists an external redemption
provider (name, callback config, retry/escalate policy, `status`). `_find_provider` (`:189`) resolves it;
inactive → `RedemptionProviderInactive` (409), missing → `RedemptionProviderNotFound` (404).

### 2.2 Initiation (`initiate_redemption` `:210`, `POST /redemption/initiate`, user, **[IDEM]**)

The gate order mirrors every money path, then the points-specific reservation:

1. **RBAC** — `require_permission` for `redemption`; reject **before** any wallet lookup or lock (`:255`).
2. **Step-up** — `enforce_step_up` runs after role but before any DB lock (`:259`).
3. **Access lock** — the redeeming user must be `active`; `txn_locked`/`suspended`/`closed` is blocked here
   (migration 0045, `:294`).
4. **Points reservation** — `lock_account_for_update(session, user_points.id)` (`:322`) locks the user's
   `points_account` `FOR UPDATE` (**redemption owns this lock** for points-overdraft serialisation), then posts
   a PENDING `redemption` transaction that DEBITs the points account. Overdraft on points is rejected under the
   lock — the derived points balance can't go negative.
5. **Provider dispatch after commit** — the external provider call happens only after the DB transaction closes
   (NFR-0130); the reservation is already durable as a PENDING row.

`_find_user_points_account` (`:93`) resolves the account; a missing one raises `UserPointsAccountMissing` (422).

### 2.3 Settlement transitions

The redemption reaches a terminal state through one of three doors, all converging on the same two internal
appliers:

| Door | Fn | Auth | Outcome |
|---|---|---|---|
| Provider callback | `process_provider_callback` (`:600`) | **HMAC** `X-Sasai-Signature` | COMPLETED or FAILED |
| Admin confirm | `confirm_redemption` (`:501`) | admin | COMPLETED |
| Admin fail | `fail_redemption` (`:550`) | admin | FAILED |

- **`_apply_completed_transition`** (`:454`) — moves the redemption + its PENDING ledger entries to COMPLETED.
  The reserved points become truly spent (the DEBIT settles). Requires the redemption to be PENDING, else
  `RedemptionNotPending` (409).
- **`_apply_failed_transition`** (`:479`) — the redemption FAILED; the points reservation is unwound by appending
  **opposite-direction** ledger legs (append-only, invariant #1 — never an UPDATE), restoring the user's points
  balance. The row moves to REVERSED.
- `process_provider_callback` verifies the HMAC signature in-service (public endpoint, HMAC-authenticated), then
  routes to the matching applier based on the provider's reported outcome. Retry/escalate behaviour comes from
  the provider's registered policy.

---

## 3. Reconciliation (`modules/reconciliation/service.py`)

Reconciliation is the safety net for redemptions that never got a callback. Auth on all endpoints is
`_require_finance_or_admin` (finance OR platform-admin realm role).

| Endpoint | Fn | Purpose |
|---|---|---|
| `POST /reconciliation/sweep` | `sweep_pending` (`:91`) | Find stale PENDING redemptions, escalate to `MANUAL_REVIEW`. |
| `GET /reconciliation/pending` | `list_pending` (`:182`) | List still-open redemptions. |
| `GET /reconciliation/manual-review` | `list_manual_review` (`:227`) | The human queue. |
| `POST /reconciliation/{id}/resolve` | `manually_resolve` (`:270`) | Force COMPLETED or REVERSED. |
| `GET /reconciliation/audit` | `query_audit_log` (`:399`) | Query the immutable audit trail (enriched). |

### 3.1 Sweep & escalate

`sweep_pending` finds PENDING redemptions older than the provider's escalation window and moves them to
`MANUAL_REVIEW` — it does **not** guess the outcome; a redemption whose external fate is unknown must be resolved
by a human, never auto-completed or auto-reversed (money-safety).

### 3.2 Manual resolution

`manually_resolve` (`:270`) requires the redemption to be in `MANUAL_REVIEW` (else
`RedemptionNotInManualReview`, 409) and an outcome of exactly COMPLETED or REVERSED (else
`InvalidResolveOutcome`, 422). A REVERSED resolution appends reversal legs via **`_flip_entries`** (`:377`) —
opposite-direction ledger entries against the *same* `transaction_id`, restoring the reserved points. This is the
append-only reversal pattern (invariant #1): the original entries are never touched; the balance nets out through
addition. Every resolution writes an `audit_log` row.

`query_audit_log` (`:399`) + `_enrich_audit_entries` (`:451`) render the audit trail human-readable — resolving
actor ids to display names (`_friendly_system_name` `:444` for system actors) and entity ids to names.

### 3.3 Celery beat status (honest note)

The reconciliation sweep is **admin/finance-triggered via `POST /reconciliation/sweep`** — it is **not** on a
Celery beat schedule. The only periodic job in `celery_app.py` `beat_schedule` is the *rewards* outbox sweep
(`rewards.recon_sweep`, every 60s — see [doc 06 §4.2](06-events-ingestion-and-mode-awareness.md)), which is a
different subsystem (draining unissued rewards, not resolving stuck redemptions). Redemption reconciliation stays
a deliberate, operator-initiated action.

---

## 4. Invariants preserved here

- **Append-only ledger (#1).** Every settlement/reversal (`_apply_failed_transition`, `_flip_entries`) appends
  opposite legs; no UPDATE/DELETE on `ledger_entries`.
- **Idempotency (#2).** `initiate_redemption` requires an `Idempotency-Key`; a replay returns the original
  redemption with no new reservation.
- **External calls after commit (#6/NFR-0130).** The provider is dispatched only after the PENDING reservation
  is committed; no external call happens inside a DB transaction or under a lock.
- **Points overdraft prevention.** Redemption's own `points_account` `FOR UPDATE` lock serialises concurrent
  redemptions so the derived points balance never goes negative — the wallet balance guard does not cover points
  accounts.

---

## 5. PRD traceability

| Requirement | Where |
|---|---|
| Pay-PRD-0660–0700 (redemption lifecycle) | `initiate_redemption`, `_apply_completed/_failed_transition` |
| Pay-PRD-0710 (provider callback + HMAC) | `process_provider_callback` |
| Pay-PRD-0720–0740 (points reservation / overdraft) | points_account `FOR UPDATE` lock at `:322` |
| Pay-PRD-0750–0780 (sweep + manual review) | `sweep_pending`, `list_manual_review`, `manually_resolve` |
| Pay-PRD-0790–0800 (audit query) | `query_audit_log` + `_enrich_audit_entries` |

---

## 6. Internal redemption — SPEC (Pay-PRD-1200–1290, planned)

> **Status: not built.** This section is the agreed design for the internal (points → own-wallet) mode.
> The external flow above is unchanged; its per-provider PTS wallet keeps being auto-created at provider
> registration (`register_provider`) — no manual wallet step exists in either mode.

### 6.1 New system accounts

| Account type | Currency | Cardinality | Purpose |
|---|---|---|---|
| `points_redemption_wallet` | PTS | 1 per tenant | Sink for internally redeemed points (the internal analogue of a provider redemption wallet). |
| `cashback_provider_wallet` | fiat | 1 per tenant **per currency** | Funds internal-redemption payouts AND rule-engine cashback rewards. Pre-funded from the bank via `treasury.adjust_system_wallet` (maker-checker), exactly like `system_cash_inflow`. |

Both are system-owned (`user_id NULL`). The `cashback_provider_wallet` joins the ledger choke-point guard
with a **non-negative floor** (same corollary as the cash float, invariant #11a): any net debit that would
drive it below zero is rejected 409 `insufficient_cashback_funds` under the row lock. Wallets for every
enabled tenant currency are created at tenant provisioning / instrument enablement.

### 6.2 Conversion-rate config

New table `points_conversion_rates`: `(tenant_id, currency, points_per_unit NUMERIC, value_per_unit NUMERIC,
max_points_per_txn NUMERIC NULL, max_balance_pct_per_txn NUMERIC NULL, status, created_at, updated_at)` —
read as "`points_per_unit` PTS = `value_per_unit` `currency`" (e.g. 100 PTS = 10.00 ZAR). The two nullable
caps bound a SINGLE redemption (Pay-PRD-1295, anti-drain): an absolute points ceiling and/or a percentage of
the user's current points balance (balance 100 + 10% → at most 10 points per transaction). NULL = uncapped
on that axis; breaching either → 422 `redemption_txn_cap_exceeded`, checked under the points lock (the
percentage is computed from the derived balance) before the burn posts. One ACTIVE row per (tenant, currency), unique-indexed. Changes ride the existing
**config change request** maker-checker (like pricing/limits) and are audit-logged. **Fail-closed
(Pay-PRD-1220):** no ACTIVE row for the requested currency → 422 `conversion_rate_missing` before any ledger
write. No default rate, ever.

### 6.3 Initiation flow (`POST /redemption/internal`, user, [IDEM])

Gate order mirrors `initiate_redemption` (§2.2), then diverges after the reservation because there is no
external dependency:

1. RBAC (`redemption` permission) → step-up (threshold vs `points_amount`) → account `active`.
2. Resolve the ACTIVE conversion rate for the requested currency (fail-closed) and compute
   `fiat_amount = points_amount × value_per_unit / points_per_unit`, rounded to the currency's minor unit.
3. **Pricing + limits fail-closed (invariant #12)** for the new transaction types — a zero-fee internal
   redemption must be an explicit pricing row.
4. **Burn first** (`redemption_internal`, PTS): lock the user's `points_account` FOR UPDATE (points
   overdraft guard, same as §2.2), check the derived balance, enforce the rate row's per-transaction caps
   (absolute + %-of-balance, Pay-PRD-1295) against that same derived balance, then DEBIT user points →
   CREDIT `points_redemption_wallet`. `post_transaction` commits, so check+debit are atomic under the lock.
5. **Payout second** (`redemption_internal_payout`, fiat): DEBIT `cashback_provider_wallet(currency)` →
   CREDIT user `financial_wallet(currency)` — floored at the choke point; normal receive caps apply (a
   payout is user-initiated, not a cap-exempt reward). **A payout failure posts an append-only compensating
   reversal of the burn** (`{key}:unwind`, `is_reversal=True`) before the error propagates — the pair is a
   two-step saga with compensation, not one DB transaction (`post_transaction` commits per call).
6. Both transactions settle **COMPLETED immediately** — no PENDING state, no callback, no reconciliation
   involvement. A single client `Idempotency-Key` covers the pair (payout key derived as `"{key}:payout"`),
   so a replay — including one after a crash between the legs — resumes idempotently and returns the
   original result without a second burn or payout.

Two separate transactions (not one 4-leg transaction) keep each currency's ledger self-balancing — the
`ledger_sum_to_zero` invariant holds per transaction in one currency. Cross-tracing comes from the shared
reference (§6.4).

### 6.4 Cross-referencing (Pay-PRD-1260)

A new `internal_redemptions` row `(id, tenant_id, user_id, points_txn_id, payout_txn_id, currency,
points_amount, fiat_amount, rate_snapshot, created_at)` binds the pair; both transactions carry
`internal_redemption:<id>` in `external_reference` (`reference` is the 40-char customer-facing code). Either leg resolves to the other in txn detail, statements, and admin ledger views. The
rate is **snapshotted** on the row — later rate changes never reinterpret history.

### 6.5 Cashback rewards re-pointing (Pay-PRD-1270)

`issue_cashback_reward` (rewards/service.py) changes its DEBIT leg from `system_cash_inflow` to the
currency-matching `cashback_provider_wallet`. Everything else (budget check before ledger write,
deterministic idempotency key, receive-cap exemption for rewards) is unchanged. Operationally this separates
promo liability (cashback wallet) from customer-money float (cash inflow) — the float can no longer be
drained by reward campaigns.

### 6.6 Failure & reversal story

An underfunded cashback wallet fails the payout AFTER the burn; the flow compensates the burn inline
(append-only reversal) and surfaces 409 `insufficient_cashback_funds` — the attempt nets to zero. Post-hoc
correction is an admin operator action that posts a compensating pair (opposite legs on both sides, new
transactions, append-only), cross-referenced to the original `internal_redemptions` row and audit-logged.
Reconciliation (§3) is not involved — nothing can get stuck.

### 6.7 UI surfaces

- **Admin — Conversion rates**: per-currency list (rate, status, last change), add/edit via config change
  request; empty state states the fail-closed rule.
- **Admin — Cashback wallets**: balance per currency + "Fund wallet" action (treasury maker-checker), and
  the redemption/cashback outflow history.
- **Mobile — Redeem**: entry from the Rewards screen; pick currency (only rate-configured currencies are
  offered), enter points with a live fiat preview at the quoted rate, PIN step-up per policy, instant
  success receipt showing both references. The external-provider flow gets its own separate UI later.

### 6.8 Build checklist (tests per coding guidelines §3)

Migrations (2 account types + `points_conversion_rates` + `internal_redemptions`), choke-point floor for the
cashback wallet, service + router, rate-config endpoints behind config-requests, mobile + admin UI. Required
tests: happy path both legs balance; `conversion_rate_missing` 422; pricing/limits fail-closed 422s;
`insufficient_cashback_funds` 409; idempotent replay (no double burn/payout); points overdraft under
concurrency; cross-reference integrity; cashback reward debits the new wallet; `ledger_sum_to_zero` stays
green.

---
