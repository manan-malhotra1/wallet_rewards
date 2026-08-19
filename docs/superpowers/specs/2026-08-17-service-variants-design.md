# Base and Derived Services — Design

**Date:** 2026-08-17 (rev. 3 — access-policy and approval decisions locked; client-impact section added)
**Status:** Draft — awaiting review. No code written. Lives on
`feature/base-derived-services`; not merged to `main`, because the
implementation carries a breaking-change risk for clients (§12).
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
| Access policy scope | **Narrower only.** A derived service may restrict user types / channels beyond its base, never widen them | A base restriction is a tenant-level control; if a derived service could widen it, creating one would become a way to bypass policy |
| Approval to create | **No maker-checker on creation.** See §6.1 | Creation yields an *unusable* service — it fails closed until priced, and pricing is already maker-checker |

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

### 6.1 Why creation needs no maker-checker

Creating a derived service is deliberately *not* an approval-gated action,
because it cannot move money or change a price on its own:

- A derived service with no `pricing_configs` row fails closed at
  `require_pricing_and_limits` — `422`, before any ledger write. Same for a
  missing `limit_configs` row (invariant #12).
- Pricing has **no direct mutation endpoint at all** (`pricing/router.py`
  exposes only `/quote`); every pricing change goes through the
  `config_requests` maker-checker flow, where `pricing` is one of the
  approved config types. Limits are the same.

So the money-affecting step is already gated, and gating creation too would
add a second approval for an inert row. The audit trail still records
`service.created` with the actor, and the "Not yet usable" state is visible
in the UI (§9), so nothing is silent.

### 6.2 Access policy is narrowing-only

At resolution time the effective policy is the **intersection** of the base's
policy and the derived service's, not a replacement:

- `allowed_user_types`: effective = base ∩ derived (NULL/empty on either side
  means "unrestricted on that dimension" and contributes no restriction).
- `allowed_channels`: same intersection rule.

Validation rejects a derived policy that names a user type or channel its
base excludes → `422 policy_wider_than_base`, so the impossible
configuration cannot even be saved. Enforcing the intersection at resolution
*as well* is deliberate belt-and-braces: if a base is later narrowed, every
derived service tightens with it automatically instead of silently outliving
the restriction.

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

## 12. Client impact — mobile app and partner API

**The API contract is additive: no client is forced to change.**
`service_code` is optional on every money endpoint, `kind` and
`base_service_code` are new response fields, and the migration backfills
every existing row to `kind='base'`. A client that ignores all of it keeps
working byte for byte.

**But a derived service produces `transaction_type` values no existing client
has seen**, and that is where the real risk sits. Audit of `mobile/`:

| Place | Behaviour with a derived code | Verdict |
|---|---|---|
| `GET /identity/me/services` → home tiles (`lib/api/wallet.ts:74`) | A derived service appears automatically as its own tile with its own `display_name`, already filtered by user type + `mobile` channel | **Works — no change needed.** This also answers old Open Question 5: customer-facing discovery already exists |
| `pricing.ts` fee quote | Takes a service code; the file's own comment notes "new services need no new client" | **Works** |
| `transactionTitle()` (`wallet.ts:98`) | Falls through to `transaction_type.replace(/_/g, ' ')` → `cashout_atm` renders as "cashout atm" | **Degrades — cosmetic.** Lower-cased, unpunctuated label |
| `activityCategory()` (`wallet.ts:121`) | Falls through to `'generic'` → wrong colour tint, and a derived P2P loses its sent/received distinction | **Degrades — visible** |
| `transactions.tsx:39` filter | `t.transaction_type === 'p2p'` — a derived P2P **disappears from the "Sent" tab** while still being in the full list | **Bug.** A transaction the user made becomes unfindable under a filter |

The pattern is clear: everywhere the app is **data-driven** it works; every
place with a hardcoded `=== 'p2p'` breaks, because that comparison assumes
the set of codes is closed. Which is exactly the assumption this design
invalidates.

### 12.1 Required API addition — expose the base on transactions

Clients must be able to group by flow without knowing every derived code
that will ever exist. So transaction read models
(`WalletTransaction`, admin transaction lists, statements) gain:

- `base_transaction_type: str` — the base code, equal to `transaction_type`
  for transactions on a base service.

Clients then compare against `base_transaction_type` for behaviour
(filters, icons, sent/received logic) and display `transaction_type` /
the service's `display_name` for labels. This is the one change that makes
derived services safe for every current and future client, so it is **in
scope for phase one, not optional**.

Denormalising it onto `transactions` (rather than joining the catalog on
read) is the right call: it keeps history immutable and correct even if a
derived service is later deleted, and matches how the ledger already stores
facts rather than re-deriving them.

### 12.2 Client work required before any derived service goes live

Ordered by severity. None of it is needed to *merge* the backend, but a
derived service must not be created in production until items 1–2 ship.

1. **`transactions.tsx` filters** → compare `base_transaction_type`. (Bug.)
2. **`activityCategory()`** → key off `base_transaction_type`. (Visible.)
3. **`transactionTitle()`** → prefer the service `display_name` from
   `/me/services` when available, else the existing fallback. (Cosmetic.)
4. **Partner API consumers** → third parties reading `transaction_type` from
   webhooks or reports may have the same hardcoded assumption. Their
   contract must be versioned or documented before a derived service is
   enabled for a partner-facing flow. This is the item with the longest
   lead time, because it involves other people's release cycles.

### 12.3 Rollout sequencing

The safe order, which the implementation plan must follow:

1. Ship the backend (columns, registry, resolution, `base_transaction_type`)
   — inert, because no derived service exists yet.
2. Ship the mobile fixes (§12.2 items 1–3) and let them reach users.
3. Ship the admin UI create flow.
4. Only then create the first derived service, in a non-production tenant.

Steps 1–3 are independently releasable and each is a no-op for users until
step 4. That is what turns a breaking change into a sequenced one.

## 13. Open questions for review

**Resolved (rev. 3):**

- ~~May a derived service be wider than its base?~~ **No — narrowing only**,
  enforced at both save time and resolution time (§6.2).
- ~~Maker-checker on creation?~~ **No** — creation yields an unusable row and
  pricing/limits are already maker-checker (§6.1).
- ~~Customer-facing discovery?~~ **Already exists** —
  `GET /identity/me/services` drives the mobile home tiles, so a derived
  service surfaces automatically (§12).

**Still open:**

1. **Naming in the UI.** "Derived service" is accurate but internal.
   "Product", "tariff", or "service variant" may read better to a
   commercial audience. The data model is unaffected.
2. **Deleting a derived service** that has pricing/limit configs and
   historical transactions: block until unpriced, or soft-delete and leave
   the configs orphaned? Historical transactions must remain readable
   either way. (Leaning: soft-delete, block if any config is still live —
   mirrors how base rows are protected.)
3. **Cap on derived services per base**, to stop catalog sprawl?
4. **Partner-API versioning** for the new `transaction_type` values
   (§12.2 item 4) — does an existing partner contract need a version bump,
   or is a documented additive change acceptable?

## 14. Non-goals

- No new money flows. A derived service never changes execution logic.
- No derived-of-derived chains.
- No pricing/limit inheritance (step-up eligibility is the single
  deliberate exception, §8).
- No change to ledger, locking, or idempotency semantics.
- No retrofit of existing base rows into derived services.
