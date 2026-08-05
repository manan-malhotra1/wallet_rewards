# 03 — Money Controls: Limits, Pricing, Roles, Step-up

> **Document type:** Low-Level Design (LLD) — the *how*.
> **Purpose:** how the pre-ledger control layer is built — the checks every money path runs
> *before* `post_transaction` writes a single ledger entry: RBAC, service-access policy, the
> fail-closed pricing+limits gate, limit windows, wallet caps, step-up PIN, charge assembly,
> and reward budgets.
> **Related:** [`.claude/rules/coding-guidelines.md`](../../.claude/rules/coding-guidelines.md),
> [`.claude/rules/ledger-invariants.md`](../../.claude/rules/ledger-invariants.md),
> code in `backend/app/modules/{roles,services,pricing,limits,taxes,commissions,step_up,budgets}/`.
> **PRD modules:** 5 (Limits 0330–0380), 6 (Pricing 0390–0430), 7 (Roles 0440–0470), plus step-up
> and reward-budget additions.
> **Read first:** [README (HLD)](README.md) §5–§6 and
> [02 — Ledger, Accounts & Money Movement](02-ledger-accounts-and-money-movement.md).

---

## 1. Where this layer sits

`post_transaction` (doc 02) is the *only* thing that writes ledger entries, and it enforces
exactly three balance invariants (overdraft, cash-float floor, `max_balance`). **Everything else
that decides whether a money move may happen at all lives in this layer**, and every money service
runs it as a fixed, ordered preamble before assembling legs. The canonical order (assembled inside
each service — `payments.p2p_transfer`, `cashin.cash_in`, `cashout.cash_out`, `airtime.initiate_recharge`,
`pin_change.change_pin`, `redemption.initiate_redemption`):

```
1  assert_user_can_transact   status gate (doc 01)          → TransactionsBlocked (403)
2  require_permission          RBAC — may this user_type?    → NotAuthorised (403)
3  assert_service_allowed      WHO/HOW access policy         → ServiceNotAllowed* (403)
4  require_pricing_and_limits  FAIL-CLOSED gate (both must resolve) → ServiceNotConfigured (422)
5  check_limits                per-service min/max + rolling caps  → AmountBelow/Above, *Exceeded (422/429)
   check_wallet_send/receive   cumulative wallet caps        → WalletSend/ReceiveLimitExceeded (429)
6  enforce_step_up             PIN step-up (fail-closed)      → StepUpRequired / InvalidStepUpPin (401)
7  resolve_fee + calculate_commission + calculate_tax        (pricing/commission/tax)
8  assemble_charges            → balanced ledger legs
9  post_transaction            balance guard + commit (doc 02)
10 external provider call      after commit (airtime/redemption)
```

Steps 1–8 all raise **before any ledger write** — the ledger only ever sees a fully-validated,
fully-priced, balanced transaction. Config for steps 3–7 is read here but **written only through
the maker-checker** ([doc 04](04-maker-checker-and-approvals.md)); the modules below expose
read/`GET` endpoints and internal CRUD functions that the config-request apply path calls.

---

## 2. Roles & permissions — `modules/roles/` (Module 7)

User-side RBAC answers one question: *may this user_type initiate this `transaction_type`?* It is
**step 1 of authorization** and is deliberately coarse (per-type, not per-user).

- **Model:** `Role` → many `RolePermission(transaction_type)`; users are bound via `UserRole`.
- **Enforcement:** `has_permission(session, user, txn_type)` resolves the user's roles and checks
  for a matching permission; `require_permission(...)` wraps it and raises `NotAuthorised` (403)
  on a miss. Every money service calls `require_permission` immediately after the status gate.
- **Admin CRUD:** `create_role`, `update_role`, `set_permission`, `remove_permission`,
  `assign_role_to_user`, `remove_role_from_user` (all `admin` endpoints under `/api/v1/roles`,
  `/api/v1/users/{id}/roles`). Not maker-checker governed (Phase-2 candidate).

RBAC is *coarse* authorization ("can this class of user do P2P at all"); the *access policy* below
is finer ("…on this channel, for this service").

---

## 3. Service access policy — `modules/services/` (Module 14 catalog, enforced here)

The service catalog defines each `transaction_type` and carries two access lists that
`assert_service_allowed(session, service, user, channel)` enforces on every money path (step 3):

| Field | Question | On violation |
|---|---|---|
| `allowed_user_types` | **WHO** may use this service | `ServiceNotAllowedForUserType` (403) |
| `allowed_channels` | **HOW** (mobile / web / partner-api / agent) | `ServiceNotAllowedOnChannel` (403) |

An empty/unset list means "no restriction on this axis". This is where, e.g., `cash_in` is fenced
to agent user-types and `merchant-cashin` to the partner API channel. Catalog CRUD is documented in
[doc 08](08-tenancy-config-and-provisioning.md).

---

## 4. Limits — `modules/limits/` (Module 5)

Two distinct limit families live here, with different enforcement points.

### 4.1 Per-service limits — advisory, checked in the service (step 5)

`check_limits(session, tenant, service, user, amount, currency)` resolves the applicable
`LimitConfig` (type-aware, see §7) and enforces, in order:

- **Per-transaction band:** `min_amount` / `max_amount` → `AmountBelowMin` / `AmountAboveMax` (422).
- **Rolling window caps** — daily / weekly / monthly, each on two axes (**count** and **value**),
  via `_aggregate_user_txns` summing the user's prior transactions in the window:
  `Daily/Weekly/MonthlyCountExceeded` and `…ValueExceeded` (all 429).

These are *advisory* thresholds, not part of the ledger guard — they read a derived aggregate and
so are not self-serializing (acceptable: they are policy ceilings, not the overdraft invariant).

### 4.2 Cumulative wallet caps — the send/receive rolling caps + `max_balance`

Wallet-limit configs (`WalletLimitConfig`, per currency, financial instruments only) carry
cross-service cumulative caps that don't belong to any single service:

- `check_wallet_send_limits` / `check_wallet_receive_limits` — cumulative **send** and **receive**
  totals across *all* services, on daily/weekly/monthly windows. `_first_wallet_window_breach`
  reports the tightest breached window → `WalletSend{window}{axis}Exceeded` /
  `WalletReceive{window}{axis}Exceeded` (429). Checked in the service (step 5).
- **`resolve_max_balance(session, tenant, user, currency)` → the ceiling the ledger guard uses.**
  This one function is called **inside `post_transaction`'s balance guard** (doc 02, invariant #11),
  *not* in the service — it is the single source of the `max_balance` value the guard enforces on
  any net credit to a `financial_wallet`. Keeping it in the guard is what makes the ceiling
  race-safe under the `FOR UPDATE` lock (the M-01 fix); re-deriving it per-endpoint would reintroduce
  the check-then-act race.

`limit_config_exists(...)` is the amount-agnostic existence probe the fail-closed gate calls (§6).
`list_my_limits` powers the mobile `/me/limits` snapshots.

---

## 5. Pricing, commission & tax — `modules/{pricing,commissions,taxes}/` (Module 6)

### 5.1 Fee resolution — `pricing.resolve_fee` / `calculate_fee`

Fees are **slab / amount-band** priced, type-aware:

```
fee = fixed + min(pct * amount, cap)          # 6dp, ROUND_HALF_UP
```

- `resolve_fee(...)` selects the `PricingConfig` band matching `(tenant, service, account_type,
  currency, user_type)` **and** whose `[min_amount, max_amount)` contains the amount, then computes
  the fee and returns a `FeeQuote(fee, fee_inclusive)`. If **no band matches the amount** it raises
  **`PricingConfigMissing`** (422) — there is no implicit zero-fee fallback (invariant #12).
- `fee_inclusive` decides whether the fee is carved out of the principal or added on top; it flows
  into the assembler (§5.4).
- `quote_fee` is the read-only preview behind `POST /api/v1/pricing/quote` (mobile fee preview);
  `pricing_config_exists` is the existence probe for the gate (§6).

### 5.2 Commission — `commissions.calculate_commission`

Agent payout, multi-band (`create/replace/delete_commission_config_for_scope`,
`_find_commission_config`), type-aware per `(tenant, service, currency, user_type)`. Commission is
**always additive** and **cap-exempt on the receive side** — the agent's earned credit passes
`skip_receive_cap=True` into the guard so a legitimate payout is never blocked by the agent's
`max_balance` (doc 02).

### 5.3 Tax — `taxes.calculate_tax`

A per-`(tenant, currency)` overlay applying two **independent** rates: a **fee-tax** (on the service
fee) and a **commission-tax** (on the agent commission). Each has its own collection account
(`tax_service_collected`, `tax_commission_collected`) and its own inclusive/exclusive flag.

### 5.4 The charge assembler — `pricing/assembler.py::assemble_charges`

One **pure function** (no DB) turns principal + fee + commission + fee-tax + commission-tax and
**three inclusive/exclusive flags** into a fully-balanced `entries` list (ΣDEBIT == ΣCREDIT,
zero-amount legs omitted since the ledger forbids amount 0). Centralising the leg math means every
money path shares one tested implementation of the matrix instead of hand-rolling legs. The three
axes:

| Axis | Inclusive | Exclusive |
|---|---|---|
| `fee_inclusive` | fee carved **out of** the principal | fee **added on top** |
| `fee_tax_inclusive` | fee-tax carved out of the fee | added on top of the fee |
| `commission_tax_inclusive` | commission-tax carved out of the commission | added on top |

Commission is always `DEBIT commission_pool → CREDIT agent` (± its tax split). Inputs are grouped
into `ChargeAccounts` / `ChargeAmounts` / `ChargeFlags` dataclasses; output is `AssembledCharges.entries`,
handed straight to `post_transaction`.

---

## 6. The fail-closed gate — `pricing.require_pricing_and_limits` (invariant #12)

**The load-bearing safety property of this whole layer.** Before any charge assembly, every
user-facing money path calls:

```python
await require_pricing_and_limits(session, tenant, service, user, account_type, currency)
```

It resolves the acting user's `user_type`, then requires **BOTH**:

- `pricing_config_exists(...)` — a pricing config resolves for the scope, **AND**
- `limit_config_exists(...)` — a limit config resolves for the scope.

If **either** is absent it raises **`ServiceNotConfigured`** (422) **before any ledger write**. Key
properties (Pay-PRD-0420):

- **Unconditional.** Not gated by any tenant flag or environment — it always runs.
- **No silent pass-through.** A zero fee or an unlimited limit must be an *explicitly configured
  row*; the absence of config is never read as "free / limitless". There is no
  `try/except PricingConfigMissing: return 0` anywhere on a money path.
- **Tested by contract.** Every money service ships tests asserting it 422s when the pricing config
  is missing **and** when the limit config is missing (`backend/tests/**/test_*fail_closed*`,
  boundary tests). The `code-review` agent blocks any new/edited money path that skips the gate.

`resolve_fee` independently re-checks at compute time (raising `PricingConfigMissing` if no *band*
matches the specific amount), so an amount that falls outside all configured bands also fails closed.

---

## 7. Type-aware config resolution (shared across §4–§6)

Pricing, limits, commission and step-up all resolve config by the acting user's `user_type` with a
**most-specific-wins** rule: a row whose `user_type` **exactly matches** the user beats a row with
`user_type = NULL` (the tenant default). This lets an operator price/limit, say, `agent` differently
from `consumer` while a single NULL-scoped row covers everyone else. `resolve_user_type`
(`shared/utils/user_types.py`) supplies the type; each `_find_*_config` helper applies the
exact-beats-NULL ordering. Widening any of these type/scope sets requires re-checking every consumer
(schema Literals, UI unions, seed) in the same pass.

---

## 8. Step-up PIN — `modules/step_up/` (auth control, Module 5/7 area)

`enforce_step_up(session, tenant, service, user, amount, currency, pin)` is **fail-closed** and runs
at step 6 (after limits, before charge assembly):

- It looks up the step-up policy for `(tenant, txn_type, currency)`.
- **The PIN is skipped only when a policy EXISTS *and* `amount <= policy.threshold_amount`.**
  In every other case a PIN is required:
  - **No policy configured** → PIN required for *any* amount (reported threshold `0`) →
    `StepUpRequired` (401) if none supplied. (Fail-closed: a missing policy never means
    "step-up disabled".)
  - Amount over threshold, no PIN → `StepUpRequired` (401).
  - Wrong PIN → `InvalidStepUpPin` (401).

Both rejections are **pre-ledger**, which is what makes the mobile step-up UX safe: the client fires
the transaction with no PIN, catches the 401, prompts for the PIN, and **replays with the same
idempotency key** (doc 10) — the first attempt never touched the ledger, so the reuse is safe.
Policy writes go through the config maker-checker (config_type `step_up`, doc 04).

---

## 9. Reward budgets — `modules/budgets/` (WAL-50)

Caps on reward *issuance* value (rewards-adjacent, but a money-control choke point).
`check_budget_available(session, tenant, scope, window, amount)` enforces a windowed cap under a
**`SELECT … FOR UPDATE`** lock so two concurrent issuances can't both pass a check that only one
should — the same self-serialization discipline as the ledger guard. Windows (`_window_floor`):
`rolling_24h`, `rolling_7d`, `calendar_month`, `lifetime`; consumption is
`SUM(reward_events.reward_value)` within the window floor. Over-cap → `BudgetExceeded` (409). CRUD:
`create_budget`, `list_budgets_for_tenant` (with live consumption), `delete_budget`
(`/api/v1/budgets`, admin). Applied by the rewards issuance path (doc 05).

---

## 10. Requirement map

| Requirement | Built as |
|---|---|
| Pay-PRD 0330–0380 (limits & thresholds) | `limits.check_limits`, wallet send/receive caps, `resolve_max_balance` (guard-called) |
| Pay-PRD 0390–0430 (pricing engine) | `resolve_fee`/`calculate_fee` slab bands, `assemble_charges`, commission + tax overlays |
| Pay-PRD 0420 (fail-closed pricing+limits) | `require_pricing_and_limits` → `ServiceNotConfigured` (422), unconditional |
| Pay-PRD 0440–0470 (roles & permissions) | `roles.has_permission` / `require_permission` (step 1 auth) |
| Service access policy (Module 14) | `services.assert_service_allowed` (WHO/HOW) |
| Step-up PIN (auth control) | `step_up.enforce_step_up` fail-closed |
| Reward budgets (WAL-50) | `budgets.check_budget_available` (FOR-UPDATE, windowed) |

**Invariants #11 and #12** (ledger guard + fail-closed) are the two this layer is accountable for;
their enforcement points are `post_transaction`'s balance guard and `require_pricing_and_limits`
respectively. See [`.claude/rules/ledger-invariants.md`](../../.claude/rules/ledger-invariants.md).
