# Base and Derived Services — Design

**Date:** 2026-08-17 (rev. 2 — base/derived model replaces the nullable-base draft)
**Status:** Draft — awaiting review. No code written.
**Scope:** `backend/app/modules/{services,pricing,limits,payments,cashin,cashout,airtime,redemption,external}`, `admin-ui/app/(authenticated)/services`. New Alembic migration. No ledger-invariant changes.

## 1. Problem

Two related gaps, both surfaced while demonstrating the Services tab.

**(a) Creating a service looks like it does something. It doesn't.**
The Services catalog accepts any `code`. Nothing checks it against the
platform's implemented flows, so `school_fees` can be created, priced,
capped, shown `active` — and never transact, because no endpoint resolves to
it. The catalog is a *gate over flows that already exist*, not a definition
of new ones, but nothing in the UI or API says so.

**(b) One flow cannot carry two commercial configurations.**
Pricing (`pricing_configs`) and limits (`limit_configs`) are keyed by the
service-code string, one row per
`(tenant, transaction_type, account_type, currency[, user_type])`. So a
tenant cannot offer domestic P2P at R2 with a R5,000 daily cap *and*
diaspora P2P at R15 with a R50,000 cap. Today that needs a new hardcoded
flow — a code change and a deployment for what is purely a commercial
decision.

## 2. What a service is today (grounding)

Each money flow is a Python module with its own endpoint and a hardcoded
code (`CASH_OUT_SERVICE_CODE = "cashout"`; `"p2p"` inline in
`payments/service.py`). That code is passed to four consumers:

| Consumer | Effect |
|---|---|
| `require_permission(session, user_id, transaction_type)` | role-based authorisation |
| `resolve_fee(...)` / `require_pricing_and_limits(...)` | fee resolution, fail-closed on missing config |
| `check_limits(...)` | per-service rolling caps + per-txn bounds |
| `transactions.transaction_type` | recorded type — analytics, rewards, reconciliation |

The nine implemented codes: `p2p`, `fund`, `withdraw`, `cash_in`,
`cashout`, `merchant_cashin`, `airtime_recharge`, `redemption`,
`change_pin`. Only *execution* is hardcoded — every configuration consumer
already dispatches on a string. **That is the seam this design uses.**

## 3. Proposal — two explicit kinds of service

Every row in the catalog is one of two kinds, declared in a `kind` column.
There is no implicit or inferred distinction.

**Base service** — a flow the platform actually implements. Ships with the
product: its code exists in the registry because a module and an endpoint
exist for it. Provisioned per tenant by the platform (seed /
`provision_tenant_defaults`), never created through the tenant admin API.
A tenant can still enable/disable it and set its access policy, because
those are legitimately per-tenant decisions.

**Derived service** — created by an operator in the Services tab. It MUST
name a base service. It executes that base's flow unchanged, and carries
its own pricing, limits, channels and permitted initiators.

```
cashout          [base]      → implemented by cashout/service.cash_out
├─ cashout_atm    [derived]  → same execution; own fee table, caps, channels
└─ cashout_agent  [derived]  → same execution; own fee table, caps, channels
```

Decisions, with rationale:

| Decision | Choice | Why |
|---|---|---|
| Kind discriminator | Explicit `kind` column (`base` \| `derived`) | The base/derived distinction is the most important fact about a row; it must not live in the absence of a value |
| Who can create what | Admin API and UI create **derived only**; base rows are platform-provisioned | A base service without an implementation is dead config — problem (a) |
| Depth | Derived → base only. No derived-of-derived | Chains make fee and limit resolution ambiguous and debugging miserable |
| Config inheritance | **None.** A derived service needs its own pricing + limit rows or it 422s | Invariant #12 forbids implicit defaults; a silently inherited fee is a revenue incident |
| Recorded `transaction_type` | The **derived** code | Free slicing in analytics, rewards targeting, reconciliation |
| Derivable bases | Money-moving bases only; `change_pin` excluded | A derived copy of a non-financial flow has no fee or limit to differentiate |

## 4. Data model

Migration alters `services`:

- `kind: String(10) NOT NULL DEFAULT 'base'` — `'base'` or `'derived'`.
  The default exists only so the migration can backfill existing rows; the
  application always sets it explicitly.
- `base_service_code: String(50) NULL` — the base's code. Required for
  `kind='derived'`, and meaningless (NULL) for `kind='base'`.

Constraints make the pairing airtight, so nullness never has to be
interpreted:

```sql
CHECK (kind IN ('base', 'derived'))
CHECK ( (kind = 'base'    AND base_service_code IS NULL)
     OR (kind = 'derived' AND base_service_code IS NOT NULL) )
CHECK (base_service_code IS NULL OR base_service_code <> code)
```

`pricing_configs` and `limit_configs` need **no schema change** — their
`transaction_type` column already accepts any string, so a derived
service's configs are ordinary rows. This is why the change is cheap.

Referential integrity for `base_service_code` is enforced in the service
layer rather than by a foreign key: the base is identified by *code*, the
target row is per-tenant and soft-deletable, and an FK would fight the
existing soft-delete semantics.

A new registry replaces today's scattered literals:

```python
# app/shared/services_registry.py
BASE_SERVICE_CODES: frozenset[str] = frozenset({...nine codes...})
DERIVABLE_BASE_CODES: frozenset[str] = BASE_SERVICE_CODES - {"change_pin"}
```

This is the single source of truth for "the platform implements this code".
Introducing it also removes an existing smell — four of the nine codes are
module constants, five are inline string literals.

## 5. How a new base service ships later

A base service requires an implementation, so it arrives by deployment, not
by admin action:

1. New module + endpoint, with its code added to `BASE_SERVICE_CODES`.
2. `provision_tenant_defaults` gains the code, so new tenants get the row.
3. A data migration inserts the base row (`kind='base'`, `status='disabled'`)
   for every existing tenant. Shipping it **disabled** means no tenant
   silently gains a live money path on deploy; an operator enables it
   deliberately.

## 6. API changes

**Catalog — `POST /api/v1/services`** creates derived services only.
- `base_service_code` becomes **required**. Omitting it →
  `422 base_service_required` (with the message explaining that base
  services ship with the platform and cannot be created here).
- The named base must be in `DERIVABLE_BASE_CODES` **and** resolve to a live
  `kind='base'` row in this tenant → else `422 invalid_base_service`.
- The new `code` must not collide with any live row in the tenant (existing
  partial-unique index) and must not shadow a `BASE_SERVICE_CODES` entry →
  `422 service_code_reserved`.
- `kind` is not a client-supplied field; the endpoint sets `'derived'`.

**Catalog — `PATCH /api/v1/services/{id}`**
- `base_service_code` is **immutable**; attempting to change it →
  `409 base_service_immutable`. Re-pointing a live derived service at a
  different execution path would silently repurpose its pricing and limits.
- Editing a base row stays possible for `status`, `display_name`,
  `description` and access policy — the existing per-tenant kill-switch and
  policy controls are unchanged.

**Catalog — `DELETE`** of a base row remains blocked (it is platform
config). Deleting a derived row is allowed; whether it must first be
unpriced is Open Question 4.

**Money endpoints** accept an optional `service_code` (body field on POSTs).
Absent → the base code, i.e. today's behaviour byte for byte. Present →
resolved per §7; the resolved code then drives permission, pricing, limits
and the recorded `transaction_type`. Execution is untouched.

## 7. Resolution algorithm

One shared helper (`services/service.resolve_service_code`), so every flow
behaves identically:

1. No `service_code` supplied → return the endpoint's base code.
2. Load the live row for `(tenant_id, service_code)`; missing →
   `404 service_not_found`.
3. `status = 'disabled'` → `409 service_disabled`.
4. `kind='base'` and code equals the endpoint's base code → return it (an
   explicit request for the base is legal).
5. `kind='derived'` and `base_service_code` equals the endpoint's base code
   → return the derived code. Otherwise → `422 service_code_mismatch`
   (blocks invoking a cash-out derivative through the P2P endpoint).
6. Access policy (`allowed_user_types`, `allowed_channels`) is evaluated
   against the **resolved** row, so a derived service can be narrower than
   its base — e.g. a diaspora variant restricted to the `api` channel.

Downstream, `require_pricing_and_limits` runs with the resolved code, so a
derived service with no fee or limit configured is rejected before any
ledger write by the existing fail-closed path. That is intended: a derived
service is not usable until it is priced and capped.

## 8. Interactions and sharp edges

Places a derived service does **not** transparently inherit behaviour. Each
is deliberate, and each must be visible in the admin UI.

- **Reward rules** (`rules.transaction_type`) — a rule targeting `cashout`
  will not fire for `cashout_atm`. Right for precise targeting, a footgun
  for "why did rewards stop". Mitigation: the campaign wizard groups
  derived services under their base and warns when a base has derived
  services the rule does not cover.
- **Step-up PIN** (`STEP_UP_TRANSACTION_TYPES`, a fixed tuple) — derive it
  from the registry plus each derived service's base, so a derived service
  inherits its base's step-up eligibility. This is the one place
  inheritance is correct: step-up is a security control, and silently
  *losing* it is the dangerous direction.
- **Analytics groupings** that enumerate codes must group by base so revenue
  charts don't fragment. Service-mix views should offer both cuts (by base,
  by derived).
- **Reversals and reconciliation** need no change — they reference the
  original transaction, whose `transaction_type` already carries the derived
  code.
- **Partner API** (`external/service.py`) — partner keys should be able to
  name a derived service; diaspora vs domestic pricing is exactly a
  partner-facing distinction. In scope; same resolution helper.
- **Segments** — criteria metrics filtering on `txn_type` gain derived codes
  as valid values for free (that vocabulary is data-driven).

## 9. Admin UI

- Services table groups derived rows beneath their base, with a `Derived`
  badge and the base named. Base rows carry a `Platform` badge and no
  delete affordance.
- "New service" dialog is derived-only: a **required base-service dropdown**
  (populated from the tenant's live, derivable base rows), then code,
  display name, permitted user types and channels. The dialog states
  plainly that base services ship with the platform.
- A derived service with no pricing or limit config shows a **"Not yet
  usable"** badge linking to add each — turning the fail-closed 422 into
  guidance instead of a surprise.
- The dead-config problem is closed at the source: an arbitrary code can no
  longer be created as a base service.

## 10. Migration and backward compatibility

- Backfill: every existing row becomes `kind='base'`,
  `base_service_code=NULL`. All nine seeded codes are in the registry, so
  the new validation cannot retroactively invalidate live data.
- A pre-migration check should assert no existing tenant row has a code
  outside `BASE_SERVICE_CODES`. If one exists (dead config created before
  this change), the migration must fail loudly with the offending rows
  listed rather than guess whether to delete or convert it.
- Every money endpoint's `service_code` is optional; omitting it reproduces
  current behaviour exactly. No client change is forced.
- Rollback: dropping the columns would leave derived rows as ordinary
  catalog entries whose codes resolve to nothing, so the downgrade must
  first soft-delete `kind='derived'` rows. Documented in the migration
  docstring.

## 11. Verification

- **Registry integrity**: a test asserts every `BASE_SERVICE_CODES` entry is
  reachable by a real endpoint and vice versa, so the registry cannot rot.
- **Catalog API**: create without a base → 422; happy-path derived create;
  base not derivable (`change_pin`) → 422; base absent from the tenant →
  422; derived code shadowing a base code → 422; base mutation attempt →
  409; base delete attempt → refused; tenant isolation on all of the above.
- **Resolution**: omitting `service_code` behaves exactly as today
  (regression test asserting the recorded `transaction_type`); a derived
  code resolves and is recorded; a cash-out derivative through the P2P
  endpoint → 422; disabled derived → 409; a narrower channel policy on the
  derived row denies where the base would allow.
- **Config isolation**: base and derived with different fees produce
  different fees for the same amount; derived with no pricing → 422 **and no
  transaction row created**; derived with no limit config → 422.
- **Limit independence**: exhausting the derived service's daily cap does
  not block the base, and vice versa.
- **Step-up inheritance**: a derived service of a step-up-eligible base
  enforces step-up.
- **Ledger invariants** unchanged — sum-to-zero and append-only tests stay
  green.
- UI: derived-only create flow with the base dropdown, grouped rendering,
  "Not yet usable" badge.

## 12. Open questions for review

1. **Naming in the UI.** "Derived service" is accurate but internal.
   "Product", "tariff", or "service variant" may read better to a
   commercial audience. The data model is unaffected.
2. **May a derived service be *wider* than its base on access policy**, or
   only narrower? §7 assumes narrower-only, so a base restriction can never
   be bypassed by creating a derived service. Confirm that is the product
   rule.
3. **Does creating a derived service need maker-checker approval?** It
   enables a new priced money path, and pricing changes already go through
   config-requests — so arguably yes.
4. **Deleting a derived service** that has pricing/limit configs and
   historical transactions: block until unpriced, or soft-delete and leave
   the configs orphaned? Historical transactions must remain readable
   either way.
5. **Customer-facing discovery.** If the mobile app must show "ATM" vs
   "Agent" cash-out as user-selectable options, the catalog needs a
   customer-facing read endpoint with display metadata. Deferred here —
   confirm whether it belongs in phase one.
6. **Cap on derived services per base**, to stop catalog sprawl?

## 13. Non-goals

- No new money flows. A derived service never changes execution logic.
- No derived-of-derived chains.
- No pricing/limit inheritance (step-up eligibility is the single
  deliberate exception, §8).
- No change to ledger, locking, or idempotency semantics.
- No retrofit of existing base rows into derived services.
