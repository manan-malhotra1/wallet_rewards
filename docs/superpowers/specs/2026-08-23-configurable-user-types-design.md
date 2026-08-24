# Configurable User Types and Categories — Design

**Date:** 2026-08-23
**Status:** Draft — awaiting review. No code written.
**Scope:** `backend/app/shared/models/users.py`, new `backend/app/modules/user_types/`, `backend/app/modules/config_requests`, `backend/app/modules/identity`, `backend/app/modules/external`, `admin-ui/app/(authenticated)/user-types` and `users/_components/create-user-dialog.tsx`, plus every config dialog that offers a user-type dropdown. One Alembic migration. **No ledger-invariant changes and no change to money-path config resolution.**

## 1. Problem

Raised by management review: an operator cannot create a user type. The five
types are Python constants (`backend/app/shared/models/users.py:52-56`) backed
by a hardcoded CHECK constraint on `users.user_type`. Adding a sixth — a
diaspora sender, a corporate payer, a tiered agent — is a schema migration and
a deployment, for what is a purely commercial decision.

A second, softer problem: the five types are presented as one flat list. There
is no notion that `agent` and `super_agent` are the same kind of thing, or that
picking a type for a service charge should start by narrowing to the kind of
customer you mean.

## 2. What exists today (grounding)

```
USER_TYPE_CONSUMER = "consumer"      # users.py:52-56
USER_TYPE_AGENT = "agent"
USER_TYPE_SUPER_AGENT = "super_agent"
USER_TYPE_MERCHANT = "merchant"
USER_TYPE_HEAD_MERCHANT = "head_merchant"
```

| Consumer of `user_type` | Effect |
|---|---|
| `ck_users_user_type` CHECK (`users.py:94-97`) | Hard DB-level allowlist of the five strings |
| `resolve_user_type()` (`shared/utils/user_types.py`) | user_id → type string, one indexed lookup |
| `limit_configs.user_type`, `wallet_limit_configs.user_type` | Nullable `String(20)`; exact type beats the `NULL` default row |
| `pricing_configs.user_type`, `commission_configs.user_type` | Same precedence pattern |
| `MERCHANT_USER_TYPES` (`users.py:67`) | Gates which users a merchant-bound API key may attach to. It provisions nothing — merchant-profile + collection-account provisioning is Epic 17 and does not exist yet |
| `PARENT_TYPE_BY_CHILD` (`users.py:73`) | agent→super_agent, merchant→head_merchant; enforced in the identity service |
| `admin-ui/lib/api-types.ts:18,37` | A TypeScript literal union plus a `USER_TYPES` array |
| Four more admin-ui files | Duplicated label maps (`user-type-badge.tsx`, `user-operation-label.ts`, `policy-controls.tsx`, `create-api-key-dialog.tsx`) |

**The load-bearing fact:** every config table stores `user_type` as a plain
string. There are no foreign keys anywhere. That loose coupling is what makes
this change small — and it is also the thing that can silently break (§11).

## 3. Decisions locked

| # | Decision | Rationale |
|---|---|---|
| D1 | No **config** resolves against a category — it organises the picker, and it carries capability (§5) | Config still resolves per user *type* exactly as today, so no money path changes and the fail-closed precedence logic is untouched. Capability is a different axis: Retail means "can take a cash-out", Business means "can carry a merchant API key" |
| D2 | **Platform-wide system types + per-tenant additions** | The five base types stay global and immutable; anything an operator creates is tenant-scoped, so one client's bespoke type never appears in another's dropdowns |
| D3 | **Deactivate only, never delete** | A retired type disappears from new-config pickers but existing config rows and existing users keep resolving unchanged. Nothing silently reprices |
| D4 | **Every change is maker-checker** — create, relabel, retire, reactivate | Consistent with pricing, limits, commission, tax and conversion rates. "All configuration is four-eyes" stays true with no exceptions to explain |
| D5 | **Codes are immutable; only labels are editable** | Codes are join keys living in config rows with no FK to protect them |
| D6 | Categories are **fixed at three**, system-seeded, not creatable in v1 | YAGNI. A fourth super-group is a different conversation |
| D7 | Retail and Business carry a **two-level type hierarchy**; Consumers is flat | Mirrors how the business actually works — a super-agent supervises agents, a head-merchant supervises merchants. Depth is capped at two so the resolution and provisioning logic never has to walk a tree |

## 4. Data model

### 4.1 `user_type_categories`

Seeded with exactly three rows, all `is_system = true`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `code` | `String(30)` UNIQUE | `consumer`, `retail`, `business` |
| `label` | `String(60)` | "Consumers", "Retail", "Business" |
| `display_order` | `Integer` | Picker ordering |
| `supports_hierarchy` | `Boolean` | `true` for Retail and Business, `false` for Consumers. When false, every type in the category must have a NULL parent |
| `is_system` | `Boolean` | Always true in v1 |
| `created_at` | timestamptz | |

### 4.2 `user_types`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID NULL | **NULL = system type**, visible to every tenant |
| `code` | `String(30)` | The join key written to `users.user_type` and config rows |
| `label` | `String(60)` | Display only; editable |
| `category_code` | `String(30)` FK → `user_type_categories.code` | |
| `is_system` | `Boolean` | System types cannot be relabelled, retired or reparented |
| `status` | `String(20)` | `active` \| `retired` |
| `parent_type_code` | `String(30)` NULL | NULL = a **parent (top-level) type**. Set = a **child type** hanging under that parent. §5 |
| `created_at`, `updated_at` | timestamptz | |

**Uniqueness** — two partial indexes rather than one composite, because
`tenant_id IS NULL` must be globally unique:

```sql
CREATE UNIQUE INDEX uq_user_types_system_code
  ON user_types (code) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_user_types_tenant_code
  ON user_types (tenant_id, code) WHERE tenant_id IS NOT NULL;
```

A tenant creating a code that collides with a **system** code cannot be caught
by either index (different partial predicates), so it is refused in the service
with `user_type_code_reserved` (409).

One CHECK is expressible and worth having:

```sql
CHECK (parent_type_code IS NULL OR parent_type_code <> code)
```

The remaining hierarchy rules are cross-row and live in the service (§5).

### 4.3 Seeded rows

| Category | `supports_hierarchy` | Parent type | Child type |
|---|---|---|---|
| Consumers | false | `consumer` | — |
| Retail | true | `super_agent` | `agent` |
| Business | true | `head_merchant` | `merchant` |

All five are `is_system = true`, `tenant_id = NULL`, `status = active`.
`merchant` and `head_merchant` are the two Business-category types, which is
what makes them merchant-capable (§5).
`agent` seeds with `parent_type_code = 'super_agent'` and `merchant` with
`head_merchant` — reproducing today's `PARENT_TYPE_BY_CHILD` exactly. `consumer`,
`super_agent` and `head_merchant` seed with a NULL parent.

## 5. Behaviour: one column, one derived rule

Without these, a custom type would appear in dropdowns and then misbehave.

**Merchant capability is derived from the category, not stored.** A user may be
bound to a merchant API key when their type sits in the **Business** category
(`category_code = CATEGORY_BUSINESS`, checked in `api_keys/service.py`). This
replaces the `MERCHANT_USER_TYPES` tuple and the short-lived
`requires_merchant_profile` boolean, which was dropped in migration `0065`. It
mirrors cash-out eligibility, which reads `CATEGORY_RETAIL` the same way in
`cashout/service.py`. Consumers / Retail / Business are exactly what the three
categories mean, and the two seeded Business types (`merchant`,
`head_merchant`) were precisely the two the flag had marked — so a tenant's own
Business type is merchant-capable the moment it is created, with no second
field to keep in step and no way for the two to disagree.

To be plain about what the old flag's name promised and never delivered:
**nothing in `backend/app/` provisions a `merchant_profiles` row or a
collection account today.** No code constructs a `MerchantProfile` at all. That
provisioning is Epic 17 work and does not exist yet; when it lands it will key
off the Business category like everything else.

**`parent_type_code`** replaces the `PARENT_TYPE_BY_CHILD` map and carries the
two-level hierarchy (D7). It is the single field that expresses tier — there is
no separate `tier` column, because one is derivable and two would be able to
disagree:

- `parent_type_code IS NULL` → a **parent (top-level) type**. `super_agent`,
  `head_merchant`, `consumer`.
- `parent_type_code` set → a **child type** hanging under the named parent.
  `agent`, `merchant`.

Five rules, all enforced in the service because all are cross-row:

1. The named parent must exist, be **active**, and sit in the **same category**.
   A Retail child cannot hang under a Business parent.
2. **The named parent must itself have a NULL `parent_type_code`.** Together with
   rule 5 this caps the tree at two levels — there is no depth counter to
   maintain and no recursion anywhere.
3. A type in a category with `supports_hierarchy = false` must have a NULL
   parent. Consumers stays flat.
4. A parent type with **active children cannot be retired**. Retiring it would
   leave children pointing at an inactive parent, and D3 forbids deletion as a
   way out. Refused with the list of blocking children; retire them first.
5. **A type that has children of its own cannot be given a parent.** Rule 2 looks
   only at the far end of the edge, so without this the cap is bypassable one
   legal step at a time: create Q and P top-level, hang C under P, then move P
   under Q and `C -> P -> Q` exists. Refused with 409 `user_type_has_children`.
   Unlike rule 4 this counts **every** child, retired included — retirement is
   reversible (D4), so allowing the move while a child is retired only defers
   the same chain. *Clearing* a parent is never blocked: it removes a level
   rather than adding one, and is the repair path for any pre-existing chain.

At the *user* level this is unchanged from today: a user of a child type must
hang under a parent user whose type is the declared `parent_type_code`, enforced
in the identity service. The type row is the declaration; the identity service
is the enforcement.

> **These are not the categories.** A category groups *types* for the picker.
> `parent_type_code` links an individual *user* to a supervising user. An agent
> and a super-agent share the Retail category **and** have a parent-child
> relationship, which is why the two concepts read as one and must not be
> merged.

## 6. Resolution and validation

`resolve_user_type()` is **unchanged** — it still reads the string off the user
row. Nothing on the money path is touched.

New helper, `list_user_types(session, tenant_id, *, include_retired=False)`:
returns system types plus that tenant's own types. `include_retired=True` is
used when rendering an existing config row so a retired type still shows its
label rather than a raw code.

The dropped CHECK is replaced by service-level validation at the two points a
type is written:

- `identity.create_user` / admin user-type change — the type must exist, be
  active, and be visible to the acting tenant, else 422 `unknown_user_type`.
- Any config create/update carrying a `user_type` — same check, so a limit
  cannot be written against a type that does not exist.

Type create/update additionally validates the four hierarchy rules in §5, each
with its own error code so the UI can point at the offending field:
`parent_type_not_found`, `parent_type_wrong_category`, `parent_type_not_toplevel`,
`category_does_not_support_hierarchy`. Retiring a parent with active children is
refused with `user_type_has_active_children` (409).

## 7. Attaching a parent user at onboarding

Type-level `parent_type_code` (§5) says *which type* a child's supervisor must
be. This section covers attaching *the actual supervising user* when an agent or
merchant is onboarded.

### 7.1 What already works

`users.parent_user_id` exists, `CreateUserRequest.parent_user_id` is already
accepted, and `identity/service.py:187-204` already validates it correctly:

- A type with no hierarchy slot must have a NULL parent, else
  `InvalidUserTypeParent`.
- For agent and merchant the parent is **already optional** — "parent is
  optional, but when present it must be the right type AND live in the same
  tenant".
- Cross-tenant parents are already refused.

So neither the column nor the optionality is new work. Only the two rules in §5
change here: `expected_parent_type` stops coming from the hardcoded
`PARENT_TYPE_BY_CHILD` map and starts coming from the child type's
`parent_type_code` row, which is what makes it work for custom types.

### 7.2 Attach by identifier, not by UUID

The field is a raw `parent_user_id: UUID` today. No operator and no partner has
a UUID to hand — they have a phone number. Both onboarding surfaces gain an
alternative:

```
parent_identifier: { identifier_type: "phone" | "email" | "account" | "card",
                     identifier_value: str } | None
```

Rules:

- `parent_identifier` and `parent_user_id` are mutually exclusive; supplying
  both is 422 `parent_reference_ambiguous`.
- Supplying neither is **valid** — the user is created with no supervisor. This
  is the normal case and must stay frictionless.
- The identifier resolves within the acting tenant only, reusing the existing
  resolution path. Unresolvable → 422 `parent_not_found`, with no distinction
  between "no such user" and "user in another tenant" (no existence leak).
- A resolved parent is then subject to the §7.1 type check unchanged.

### 7.3 Partner onboarding API

`ExternalCreateUserRequest` currently forces `consumer` with no parent, so a
partner cannot onboard an agent or a merchant at all. It gains optional
`user_type` and `parent_identifier`, validated exactly as the admin path is —
the API-key tenant is still the only tenant in play, and an unknown or retired
type is still refused.

This is a widening of a deliberately narrow endpoint. The narrowness was a
safety property, so the type must be validated against the tenant's own
resolved list (§6) and never trusted from the body beyond that.

### 7.4 Admin UI

In `users/_components/create-user-dialog.tsx`, when the chosen type is a **child
type** (its `parent_type_code` is set), an optional "Supervisor" block appears:

1. A phone-number field with a **Look up** action — deliberately not a
   free-text id, and deliberately not a dropdown of every super-agent, which
   does not scale past a few dozen.
2. On success the resolved user's **name, type and masked phone** are shown for
   confirmation before the dialog will accept them. Attaching the wrong
   supervisor is a commercially meaningful mistake, so the operator confirms a
   person, not a search result.
3. A **Clear** action detaches, since the field is optional.
4. If the resolved user is the wrong type, the inline error names the type
   required — "must be a Super agent" — rather than a generic failure.

The block is absent entirely for top-level and Consumers types. `user-lookup-form.tsx`
already implements the phone-lookup pattern; the new component follows it rather
than inventing a second one.

**Governance:** attaching a parent is part of user creation and inherits
whatever approval user creation already carries. It is **not** covered by D4 —
that decision governs user-*type* configuration, not individual user records.

### 7.5 Attaching a supervisor after the fact

Out of scope for this spec, and called out so it is a decision rather than an
omission: the same lookup belongs in `edit-user-drawer.tsx` for agents already
onboarded without a supervisor. It needs its own thinking about whether
re-parenting a live agent affects commission attribution on historical
transactions, which is a question this spec should not answer in passing.

## 8. Maker-checker

`user_type` joins the config-request registry alongside `pricing`, `limit`,
`wallet_limit`, `commission`, `tax`, `step_up`, `conversion_rate`. All four
operations — create, relabel, retire, reactivate — are proposals landing in the
Configuration tab of `/approvals`, requiring a distinct approver.

**Prerequisite:** the `ConfigType` Literal in `config_requests/schemas.py` must
gain `user_type`. FastAPI validates that Literal before any registry lookup
runs, so omitting it produces a 422 that looks like a broken registry — the
exact failure mode hit when `conversion_rate` was added.

## 9. Admin UI

**New page `/user-types`.** Three category sections in `display_order`. Retail
and Business render as a two-level list — each parent type with its children
indented beneath it; Consumers renders flat. Every row carries a status pill and
a "System" badge where immutable. Editing a system type is not offered — the
affordance is absent, not disabled-with-a-tooltip.

**Create dialog.** Pick the category first, then, when that category supports
hierarchy, a required choice:

- **A parent type** — stands at the top level and can have children of its own.
- **A child type** — followed by a parent dropdown listing only active
  top-level types in the chosen category.

For Consumers the choice is not shown at all, since the category is flat. The
parent dropdown never offers a child type, so a user cannot construct a third
level through the UI even before the service refuses it.

**New shared `<UserTypeSelect>`.** Category dropdown, then a type dropdown
filtered to that category. Replaces the flat list in:

- `limits/_components/create-limit-dialog.tsx`
- `limits/_components/create-wallet-limit-dialog.tsx`
- `commissions/_components/create-commission-dialog.tsx`
- `taxes/_components/create-tax-dialog.tsx`
- `services/_components/policy-controls.tsx`
- `api-keys/_components/create-api-key-dialog.tsx` (filtered to
  Business-category types, replacing the hardcoded `MERCHANT_TYPES`)

**Type changes.** `UserType` in `lib/api-types.ts` stops being a literal union
and becomes `string`, with a `UserTypeOption { code, label, category_code }`
fetched server-side. The four duplicated label maps collapse into that one
source — removing them is part of this work, not a follow-up.

## 10. Migration and seed

One Alembic migration:

1. Create `user_type_categories`, insert the three system rows.
2. Create `user_types` and both partial unique indexes.
3. Insert the five system types with their flags (§4.3).
4. **Drop `ck_users_user_type`.**

Steps 1–3 are additive and reversible. Step 4 is the one-way door: downgrade
recreates the CHECK, which will fail if any custom type is already in use. The
downgrade must therefore assert that no non-system type exists and abort with a
clear message rather than half-applying.

## 11. Risks

**Dropping the CHECK trades a database guarantee for an application one.** This
is unavoidable — dynamic types cannot live behind a static allowlist — but it is
a real reduction in defence depth. Mitigation is a test asserting user creation
with an unknown type is refused, not care.

**Silent fallback if a type ever vanishes.** Config rows reference `user_type`
by string with no FK. If a user carried a type that no longer resolved,
`resolve_user_type` would still return the string, the config lookup would find
no exact match, and it would fall back to the `user_type IS NULL` default row —
the user would quietly get **default pricing and limits instead of being
refused**, which is exactly what invariant #12 exists to prevent. D3
(deactivate, never delete) is the structural defence: a retired type still
resolves. This risk is the reason deletion is not offered at all.

**Retired types must stay resolvable.** A retired type is excluded from new
config pickers but must continue to resolve for existing users and existing
config rows. A test covers this explicitly.

## 12. Testing

| Area | Scenario |
|---|---|
| Tenant isolation | Tenant A cannot see, use or retire tenant B's custom type |
| System immutability | Relabel/retire/reparent of a system type → 403 |
| Code collision | Tenant creating code `consumer` → 409 `user_type_code_reserved`; duplicate tenant code → 409 |
| Validation | User creation with an unknown or retired type → 422 `unknown_user_type` |
| Retired resolution | A retired type is absent from the picker list but still resolves for an existing user and an existing config row |
| Derived behaviour | A custom Business type may be bound to a merchant API key and a custom Consumers/Retail type may not; a custom child type enforces its `parent_type_code` |
| Hierarchy — happy path | A new parent type under Retail, then a new child under it; a user of the child type must hang under a parent user of that parent type |
| Hierarchy — depth cap | Creating a child whose parent is itself a child → 422 `parent_type_not_toplevel`. This is the two-level guarantee |
| Hierarchy — cross-category | A Retail child naming a Business parent → 422 `parent_type_wrong_category` |
| Hierarchy — flat category | A Consumers type with any parent → 422 `category_does_not_support_hierarchy` |
| Hierarchy — self-reference | `parent_type_code = code` → rejected by the CHECK |
| Parent attach — omitted | An agent created with no supervisor succeeds and stores a NULL `parent_user_id` |
| Parent attach — by phone | `parent_identifier` resolves and attaches; both `parent_identifier` and `parent_user_id` together → 422 `parent_reference_ambiguous` |
| Parent attach — wrong type | Attaching a consumer as an agent's supervisor → 422 `InvalidUserTypeParent` |
| Parent attach — cross-tenant | A phone belonging to another tenant's super-agent → 422 `parent_not_found`, with no existence leak |
| Parent attach — partner API | A partner can onboard an agent with a supervisor; an unknown or retired `user_type` is still refused |
| Hierarchy — retire guard | Retiring a parent with active children → 409 `user_type_has_active_children`; succeeds once the children are retired |
| Hierarchy — re-parent guard | Q + P top-level, C under P, then moving P under Q → 409 `user_type_has_children`, retired C included; moving a childless type still succeeds, and clearing a parent is never blocked |
| Maker-checker | Create requires approval; the same admin cannot approve their own proposal; an approved proposal makes the type selectable |
| Regression | The five seeded types resolve identically to the pre-migration constants across limits, pricing, commission and tax |

## 13. Out of scope

- Category CRUD (D6). Three fixed categories only.
- Category-level config with inheritance. Explicitly rejected as D1 — it would
  add a precedence tier to fail-closed resolution on every money path.
- Bulk reassignment of users between types.
- Attaching or changing a supervisor **after** onboarding (§7.5).
- Hierarchies deeper than two levels (D7). A third tier would require walking a
  tree in provisioning and identity validation, both of which are flat lookups
  today.
- Re-parenting a type that **has children of its own** (§5 rule 5). Re-parenting
  a *childless* type IS supported — the edit dialog exposes it and the guard
  makes it safe. Moving a type that is itself a parent would deepen the tree past
  the two-level cap; create the correctly-parented type and retire the old one
  instead.
- Mobile app changes. No mobile surface displays or selects user types.
- Renaming existing type codes (D5).
