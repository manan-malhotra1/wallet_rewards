# Service Variants — Design

**Date:** 2026-08-17
**Status:** Draft — awaiting review. No code written.
**Scope:** `backend/app/modules/{services,pricing,limits,payments,cashin,cashout,airtime,redemption,external}`, `admin-ui/app/(authenticated)/services`. New Alembic migration. No ledger-invariant changes.

## 1. Problem

Two related gaps, both surfaced while demonstrating the Services tab.

**(a) Creating a service looks like it does something. It doesn't.**
The Services catalog lets an admin create a row with any `code`. Nothing
validates that code against the platform's implemented flows, so
`school_fees` can be created, given pricing and limit configs, shown as
`active` — and never transact, because no endpoint resolves to it. The
catalog is a *gate over flows that already exist*, not a definition of new
ones, but the UI does not say so. This is latent operator confusion and a
support ticket waiting to happen.

**(b) One flow cannot carry two commercial configurations.**
Pricing (`pricing_configs`) and limits (`limit_configs`) are both keyed by
the service-code string. There is exactly one row per
`(tenant, transaction_type, account_type, currency[, user_type])`, so a
tenant cannot offer — for example — domestic P2P at R2 with a R5,000 daily
cap *and* diaspora P2P at R15 with a R50,000 cap. Today the only way is a
new hardcoded flow, which is a code change and a deployment for what is
fundamentally a commercial decision.

## 2. What a service is today (grounding)

Each money flow is a Python module with its own endpoint and a hardcoded
code — `CASH_OUT_SERVICE_CODE = "cashout"`, `"p2p"` inline in
`payments/service.py`, and so on. That constant is passed to four places:

| Consumer | Keyed by | Effect |
|---|---|---|
| `require_permission(session, user_id, transaction_type)` | code | role-based authorisation |
| `resolve_fee(...)` / `require_pricing_and_limits(...)` | code | fee resolution, fail-closed on missing config |
| `check_limits(...)` | code | per-service rolling caps + per-txn bounds |
| `transactions.transaction_type` | code | the recorded transaction type (analytics, rewards, reporting) |

The nine live native codes: `p2p`, `fund`, `withdraw`, `cash_in`,
`cashout`, `merchant_cashin`, `airtime_recharge`, `redemption`,
`change_pin`. Only the *execution* is hardcoded — every configuration
consumer above already dispatches on a string. **That is the seam this
design uses.**

## 3. Proposal

Introduce a **service variant**: a named catalog entry that executes an
existing native flow unchanged, but carries its own pricing, limits and
recorded `transaction_type`.

```
p2p            (native)   → implemented by payments/service.p2p_transfer
├─ p2p_domestic (variant)  → same execution, own fee table + caps
└─ p2p_diaspora (variant)  → same execution, own fee table + caps
```

Decisions taken, with rationale:

| Decision | Choice | Why |
|---|---|---|
| Depth | One level only — a variant's base must be native | Chains make fee/limit resolution ambiguous and debugging miserable |
| Config inheritance | **None. Strict.** A variant needs its own pricing + limit rows or it 422s | Invariant #12 forbids implicit defaults; a silently-inherited fee is a revenue incident |
| Recorded `transaction_type` | The **variant** code | Free slicing in analytics, rewards targeting, reconciliation |
| Native code validation | Enforced on create — a non-variant code must be in the platform registry | Closes problem (a) |
| Variant eligibility | Only money-moving natives; `change_pin` excluded | A variant of a non-financial flow has no fee or limit to differentiate |

## 4. Data model

Migration adds two nullable columns to `services`:

- `base_service_code: String(50) NULL` — NULL means native; non-NULL names
  the native flow this variant delegates to.
- No other schema change. `pricing_configs` and `limit_configs` need
  **nothing** — their `transaction_type` column already accepts any string,
  so a variant's configs are ordinary rows.

Constraints:

- `CHECK (base_service_code IS NULL OR base_service_code <> code)` — a
  variant cannot be its own base.
- The existing partial-unique `(tenant_id, code) WHERE deleted_at IS NULL`
  already prevents duplicate variant names.
- Referential integrity for `base_service_code` is enforced in the service
  layer, not by FK: the base is identified by *code*, and the target row is
  per-tenant and soft-deletable, so an FK would fight the existing
  soft-delete semantics.

A new module-level registry replaces today's scattered literals:

```python
# app/shared/services_registry.py
NATIVE_SERVICE_CODES: frozenset[str] = frozenset({...nine codes...})
VARIANT_ELIGIBLE_CODES: frozenset[str] = NATIVE_SERVICE_CODES - {"change_pin"}
```

This registry is the single source of truth for "does the platform
implement this code". Introducing it also removes an existing smell — four
of the nine codes are module constants and five are inline string literals.

## 5. API changes

**Catalog (`POST/PATCH /api/v1/services`)**
- `base_service_code: str | None` added to create and update payloads.
- Create validation:
  - `base_service_code` omitted → `code` MUST be in `NATIVE_SERVICE_CODES`,
    else `422 unknown_service_code` naming the valid set.
  - `base_service_code` provided → it MUST be in `VARIANT_ELIGIBLE_CODES`
    and MUST resolve to a live native row in this tenant, else
    `422 invalid_base_service`. The variant's own `code` must NOT be in
    `NATIVE_SERVICE_CODES` (no shadowing a platform code).
- `base_service_code` is **immutable after create** — changing it would
  silently re-point live pricing and limits at a different execution path.
  Attempting it returns `409 base_service_immutable`.

**Money endpoints**
Each money-moving endpoint accepts an optional `service_code` (body field
for POSTs). Absent → the native code, i.e. today's behaviour byte for byte.
Present → resolved per §6, and the resolved code is then used for
permission, pricing, limits and the recorded `transaction_type`. The
execution path is untouched.

## 6. Resolution algorithm

Executed once, before any ledger work, in a shared helper
(`services/service.resolve_service_code`) so all flows behave identically:

1. If no `service_code` supplied → return the endpoint's native code.
2. Load the live catalog row for `(tenant_id, service_code)`; missing →
   `404 service_not_found`.
3. Row is `disabled` → `409 service_disabled`.
4. Row is native and equals the endpoint's native code → return it (an
   explicit request for the base is legal).
5. Row is a variant and `base_service_code` == the endpoint's native code →
   return the variant code. Otherwise → `422 service_code_mismatch`
   (prevents invoking a cash-out variant through the P2P endpoint).
6. Access policy (`allowed_user_types`, `allowed_channels`) is evaluated
   against the **resolved** row, so a variant can be narrower than its base
   — e.g. a diaspora variant restricted to the `api` channel.

Downstream, `require_pricing_and_limits` runs with the resolved code, so a
variant with no configured fee or limit is rejected before any ledger
write, with the existing fail-closed error. That is the intended behaviour,
not a bug: a variant is not usable until it is priced and capped.

## 7. Interactions and sharp edges

These are the places a variant does **not** transparently inherit
behaviour. Each is a deliberate decision, and each needs to be visible in
the admin UI.

- **Reward rules** (`rules.transaction_type`) — a rule targeting `p2p`
  will not fire for `p2p_diaspora`. Correct for precise targeting, a
  footgun for "why did rewards stop". Mitigation: the campaign wizard's
  service picker groups variants under their base and warns when a base has
  variants that the rule does not cover.
- **Step-up PIN** (`STEP_UP_TRANSACTION_TYPES`, a fixed tuple) — a variant
  is not step-up eligible until added. Mitigation: derive the tuple from
  the registry plus each variant's base, so a variant inherits its base's
  step-up eligibility automatically. This is the one place inheritance is
  correct, because step-up is a security control and silently *losing* it
  is the dangerous direction.
- **Analytics / dashboard groupings** that enumerate service codes must
  group by base to avoid fragmenting revenue charts. Service-mix breakdowns
  should offer both views (by base, by variant).
- **Reversals and reconciliation** need no change: they reference the
  original transaction, whose `transaction_type` already carries the variant
  code.
- **Partner API** (`external/service.py`) — partner keys should be able to
  name a variant, since diaspora vs domestic pricing is exactly a
  partner-facing distinction. In scope; the same resolution helper applies.
- **Segments** — criteria metrics that filter by `txn_type` gain variant
  codes as valid values for free (the metric vocabulary is data-driven).

## 8. Admin UI

- Services table: variants render indented under their base with a
  `Variant` badge; the base column is visible and sortable.
- Create dialog: a "Service type" choice — *Platform service* (code picked
  from the registry's unimplemented-but-available set, or blocked entirely
  if all nine exist) or *Variant of an existing service* (base picker,
  then a free-text code + display name).
- A variant with no pricing or limit config shows a **"Not yet usable"**
  warning badge with links to add each — turning the fail-closed 422 into
  guidance instead of a surprise.
- The dead-config problem is closed at the source: an arbitrary code can no
  longer be created as a native service.

## 9. Migration and backward compatibility

- `base_service_code` is nullable and defaults to NULL, so every existing
  row becomes a native service with no data change.
- Existing seeded codes are all in the registry, so the new create-time
  validation cannot retroactively invalidate them.
- Every money endpoint's `service_code` is optional; omitting it reproduces
  current behaviour exactly. No client change is forced.
- Rollback: dropping the column leaves variants orphaned as ordinary
  catalog rows whose codes no longer resolve — so the downgrade must also
  soft-delete rows where `base_service_code IS NOT NULL`. Documented in the
  migration docstring.

## 10. Verification

- **Registry**: every code in `NATIVE_SERVICE_CODES` is reachable by a real
  endpoint (a test asserts the registry and the modules agree, so the
  registry cannot rot).
- **Catalog API**: native create with unknown code → 422; variant create
  happy path; variant of a non-eligible base (`change_pin`) → 422; variant
  whose base does not exist in the tenant → 422; variant shadowing a native
  code → 422; base mutation attempt → 409; tenant isolation.
- **Resolution**: omitted `service_code` behaves identically to today
  (regression test on P2P asserting the recorded `transaction_type`);
  variant resolves and records the variant code; cash-out variant through
  the P2P endpoint → 422; disabled variant → 409; variant narrower channel
  policy denies where the base would allow.
- **Config isolation**: base and variant with different fees on the same
  flow produce different fees for the same amount; variant with no pricing
  → 422 before any ledger write (assert no transaction row was created);
  variant with no limit config → 422.
- **Limits independence**: exhausting the variant's daily cap does not
  block the base, and vice versa.
- **Step-up inheritance**: a variant of a step-up-eligible base enforces
  step-up.
- **Ledger invariants** unchanged — the existing sum-to-zero and
  append-only invariant tests must stay green.
- UI: create-dialog variant flow, indented rendering, "Not yet usable"
  badge.

## 11. Open questions for review

1. **Naming.** "Variant" vs "tariff class" vs "product code". Variant is
   neutral and technical; tariff class is the commercial term the business
   may prefer.
2. **Should a variant be able to override the access policy to be *wider*
   than its base**, or only narrower? Narrower-only is safer (a base
   restriction cannot be bypassed by creating a variant) and is what §6
   assumes — confirm that is the desired product rule.
3. **How does the mobile app discover variants?** If the app must show
   "Domestic" and "Diaspora" as user-selectable options, the catalog needs
   a customer-facing read endpoint with display metadata. Deferred here;
   flag if it belongs in phase one.
4. **Per-variant maker-checker?** Creating a variant sets pricing indirectly
   (by enabling a new priced flow). Pricing changes already go through
   config-requests; should variant *creation* also require approval?
5. **Cap on variants per base**, to stop the catalog sprawling?

## 12. Non-goals

- No new money flows. A variant never changes execution logic.
- No variant-of-variant chains.
- No config inheritance for pricing or limits (step-up eligibility is the
  single deliberate exception, §7).
- No change to the ledger, locking, or idempotency semantics.
- No retrofit of existing tenants into variants — natives stay native.
