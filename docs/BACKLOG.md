# Backlog — Sasai Wallet & Rewards Platform

> **Purpose:** Active backlog, started 2026-08-12. The previous
> `LINEAR_BACKLOG.md` is stale and kept only as an historical record — new
> items land here.
>
> Organised as Epics × Stories with acceptance criteria. Statuses:
> `Backlog` · `In Progress` · `Done` · `Deferred` · `On Hold`.

---

## Epic B1 — Segmentation Phase 1 Hardening · **Backlog**

Segmentation Phase 1 shipped 2026-08-12 (segment groups, criteria DSL, batch
evaluator, Celery scheduling, admin API + UI — design:
`docs/superpowers/specs/2026-08-12-ai-segmentation-design.md`, plan:
`docs/superpowers/plans/2026-08-12-segmentation-phase1.md`). These are the
follow-ups deferred out of that branch by its reviews. None are blockers; the
shipped feature is complete and tested without them.

### Story B1.1 — Idempotency-Key policy for admin-config endpoints · Backlog

**Description:** Decide, repo-wide, whether admin configuration endpoints
require an `Idempotency-Key` header. Segments and segment-groups currently
follow the multipliers precedent (not required), while invariant #2 in
CLAUDE.md reads as if every mutating endpoint needs one.

**Acceptance criteria:**
- A documented decision (CLAUDE.md invariant #2 clarified, or headers added)
- Segments, segment-groups, and multipliers modules are consistent with it
- Tests updated to assert whichever behaviour was chosen

### Story B1.2 — Segment-group rename (PATCH) · Backlog

**Description:** `PATCH /api/v1/segment-groups/{id}` for name/description,
plus an inline edit affordance on the group section header in the UI.

**Acceptance criteria:**
- Happy path renames; duplicate name in tenant → 409 (sqlstate 23505 mapping
  in `segments/_common.py`)
- Tenant isolation (cross-tenant id → 404)
- Audit row `segment_group.updated` with before/after state
- System groups are renameable (the flag protects deletion semantics, not
  cosmetics)
- UI test with mocked server action

### Story B1.3 — Segment delete endpoint · Done (2026-08-17, d832d36 — also added rename via PATCH)

**Description:** `DELETE /api/v1/segments/{id}`. The UI already gates a
delete affordance by role; there is no backend endpoint yet.

**Acceptance criteria:**
- Deletes the segment and its `user_segments` memberships
- Refused with 409 when the segment is bound to a rule or multiplier, naming
  the binding
- `is_system` segments refused
- Tenant isolation; audit row `segment.deleted`

### Story B1.4 — Member counts in the segments list · Done (2026-08-17, 8d4c566)

**Description:** Show per-segment membership counts on the segments page,
with a manual/criteria split.

**Acceptance criteria:**
- Counts render per segment; computed in one grouped query (no N+1)
- Manual vs criteria split visible (tooltip or subtext)
- UI test with mocked action

### Story B1.5 — DRY the Celery NullPool session bootstrap · Backlog

**Description:** The engine-per-task NullPool pattern is copy-pasted in three
places (rewards outbox, segments recompute, purge jobs). Extract one shared
helper and migrate all three.

**Acceptance criteria:**
- One helper in `backend/app/shared/`; three call sites use it
- No behaviour change; all suites green

### Story B1.6 — Recompute robustness knobs · Backlog

**Description:** Three small evaluator/task refinements: (a) `expires` on the
`segments-recompute` beat entry so a backed-up queue never stacks stale
sweeps; (b) explicit `@celery_app.task` binding instead of `@shared_task`,
removing the import-order coupling that caused the live-smoke 500; (c) a
two-connection concurrency test proving the `FOR UPDATE` serialization of
`recompute_tenant`.

**Acceptance criteria:**
- Beat entry carries `expires`
- Task binding survives an app process started without importing
  `app.celery_app`
- Concurrency test passes (second transaction blocks until the first commits)

### Story B1.7 — Per-tenant fan-out for the recompute sweep · Backlog

**Description:** `segments.recompute_all` sweeps all tenants in one task
(soft limit 540s). When tenant count or data volume grows, fan out one
`recompute_tenant` child task per tenant, keeping stalest-first ordering and
per-tenant poison isolation.

**Acceptance criteria:**
- Sweep enqueues N child tasks instead of iterating inline
- A poisoned tenant consumes only its own task's budget
- Beat cadence and audit rows unchanged

### Story B1.8 — Preview endpoint cost bound · Backlog

**Description:** `POST /segments/preview` runs the full metric computation
for the tenant. Bound it (row limit / statement timeout / cheapest-first
short-circuit) so an expensive criteria doc can't hold a worker.

**Acceptance criteria:**
- Preview on a large tenant returns within the bound
- Truncation is visible in the response (e.g. `truncated: true`)

### Story B1.9 — Ledger-entry index at scale · Backlog

**Description:** The 500k-row measurement showed the planner ignoring the
covering index for segment metrics. Re-measure at production-like volume and
decide on `ix_ledger_entries_account` (or a composite).

**Acceptance criteria:**
- Documented EXPLAIN comparison at target volume
- Index added via migration, or explicitly rejected in an ADR

---

## Epic B2 — AI-Assisted Segment Creation (Segmentation Phase 2) · **On Hold**

> **2026-08-12 — ON HOLD by product decision.** Do not plan or start any B2
> story until this hold is explicitly lifted.

The AI layer designed in
`docs/superpowers/specs/2026-08-12-ai-segmentation-design.md` but deliberately
excluded from Phase 1: per-tenant AI provider configuration and
natural-language segment creation ("users who sent more than R1000 in the
last month" → a validated criteria doc). Needs its own implementation plan
before any story starts.

### Story B2.1 — Per-tenant AI provider config · Backlog

**Description:** Tenant-scoped provider settings (provider, model, API key)
with an admin UI page.

**Acceptance criteria:**
- API key stored encrypted at rest; never logged; GET returns a masked
  read-back only
- Maker-checker on changes; audit `ai_config.updated`
- Tenant isolation; 422 on unknown provider
- No key material ever reaches the browser

### Story B2.2 — Natural-language → criteria translation endpoint · Backlog

**Description:** `POST /segments/translate` takes free text, calls the
tenant's configured AI provider (external call, so outside any DB
transaction), and returns a criteria DSL doc validated against the existing
`SegmentCriteria` schema. Never auto-creates the segment — the admin reviews
the doc in the criteria builder before saving.

**Acceptance criteria:**
- Happy path returns a schema-valid doc (mocked provider in tests)
- Schema-invalid model output retried once, then 422 with reason
- Missing provider config → 409 `ai_config_missing`, no external call
- Prompt and response audit-logged with PII masking; rate-limited per tenant

### Story B2.3 — "Describe your segment" UI · Backlog

**Description:** A free-text prompt in the create-segment dialog that calls
B2.2, pre-fills the criteria builder with the returned doc (fully editable),
and shows the live preview count before saving.

**Acceptance criteria:**
- Flow test with mocked action
- AI failure degrades to the manual builder without losing entered state

---

## Epic B3 — Admin UI Polish (post-glassmorphism) · **Backlog**

Follow-ups surfaced by the glassmorphism final review (2026-08-14). None
block the feature.

### Story B3.1 — Light-mode muted-foreground contrast · Backlog

**Description:** `--muted-foreground` in the light theme measures ~3.6:1 on
glass panels (and was already ~4.3:1 on solid white before glassmorphism) —
below WCAG AA for normal text. Darken the light-theme `muted-foreground`
derivation in `lib/brand-palette.ts` (and the globals.css default, guarded by
the palette sync test) until it clears 4.5:1 against the worst-case
atmosphere stop.

**Acceptance criteria:**
- Light `--muted-foreground` ≥ 4.5:1 on `.glass-panel` and `.glass-overlay`
  worst-case backgrounds (document the measurement)
- Dark theme unchanged (already 5.6:1+)
- Palette sync guard updated values; all UI tests green

---

## Epic B4 — Base & Derived Services · **Phase 1 done, Phases 2–3 open**

Spec: `docs/superpowers/specs/2026-08-17-service-variants-design.md` (rev. 3).
Plan: `docs/superpowers/plans/2026-08-18-base-derived-services-phase1.md`.

**Phase 1 (backend) — Done 2026-08-18** on `feature/base-derived-services`:
registry, migration 0056 (`services.kind`, `services.base_service_code`,
`transactions.base_transaction_type`), derived-only catalog API,
`resolve_service_code` with narrowing-only policy intersection, all money
flows wired (P2P, cash-in, cash-out, airtime, redemption, partner
fund/withdraw/merchant cash-in), and the client read models. Inert:
18 base services, 0 derived.

> **Sequencing rule (spec §12.3) — SATISFIED 2026-08-18 by Story B4.1.** The
> rule was: do not create a derived service in production until the mobile
> client groups by base, because a derived `transaction_type` reaching the old
> app made a derived P2P vanish from the "Sent" filter. The client now ships
> the fix, so derived services are safe to create — subject to the shipped
> mobile build actually being in users' hands, not just merged.

### Story B4.1 — Mobile client: group by base, not by exact code · Done (2026-08-18, 18182f7 + eb73cd7)

**Description:** Three hardcoded `transaction_type === 'p2p'` comparisons
assume the code set is closed, which base/derived invalidates. Switch them to
the new `base_transaction_type`.

**Acceptance criteria:**
- `mobile/app/transactions.tsx` "Sent" filter keys off `base_transaction_type`
  (today a derived P2P disappears from it — the actual bug)
- `activityCategory()` in `mobile/lib/api/wallet.ts` keys off the base, so a
  derived P2P keeps its sent/received tint
- `transactionTitle()` prefers the service `display_name` from `/me/services`,
  falling back to today's behaviour (cosmetic)
- Home tiles need no change — `/me/services` is already data-driven

**Proven end to end (2026-08-18)** against a real `p2p_diaspora` derived service
in the dev DB: a R25 transfer recorded `p2p_diaspora | p2p | COMPLETED` with a
balanced 4-entry ledger, and the `/me` feed row evaluated
`sent_NEW=True, sent_OLD=False` — i.e. the bug reproduced and the fix held on
live data. `mobile-simulator` labels it "Diaspora Transfer". The service was
soft-deleted afterwards, leaving the catalog inert (18 base / 0 derived) and
the transactions in place — the ledger is append-only.

> **Config prerequisite found during that proof:** a derived service needs
> FOUR rows before it can transact — the `services` row, a `pricing_configs`
> row, a `limit_configs` row, AND a `role_permissions` grant. The first
> transfer attempt failed `NotAuthorised` because `has_permission()` matches
> `transaction_type` exactly, so a derived code inherits nothing from its
> base's grant. Story B4.2 must surface all four, not just pricing and limits.

### Story B4.2 — Admin UI: create a derived service · Partial (2026-08-18, 45b519e)

**Description:** The Services tab can't create derived services yet, so the
backend capability is unreachable.

**Acceptance criteria:**
- "New service" dialog is derived-only, with a required base dropdown fed by
  the tenant's live derivable base rows; states that base services ship with
  the platform
- Table groups derived rows under their base with a `Derived` badge; base rows
  show `Platform` and no delete affordance
- A derived service with no pricing config, no limit config, **or no role
  permission grant** shows "Not yet usable" with links to add each — all three
  are hard prerequisites (the first two fail closed with a 422, the third with
  a `NotAuthorised`; see the B4.1 note)
- Campaign wizard warns when a base has derived services a rule doesn't cover
  (rewards target the resolved code — see the spec's §8 footgun)

**Done in 45b519e:** the derived-only dialog (required base dropdown fed by
`ServiceOut.derivable`, policy chips constrained to the base, empty-policy dead
end blocked in the form) and the grouped table with Derived/Platform badges and
no delete on base rows. This also FIXED a break: Phase 1 made the endpoint
derived-only, so until now every create from the UI 422'd.

**Still open — both need a backend readiness signal that doesn't exist yet:**
the "Not yet usable" indicator and the campaign-coverage warning. Whether a
service can transact is currently only answerable by querying
`pricing_configs`, `limit_configs` and `role_permissions` per service, so this
wants a small readiness field or endpoint before the UI can show it. Tracked as
B4.5.

### Story B4.5 — Service readiness signal (backend + UI badge) · Done (2026-08-18, 9ffe281)

**Description:** A newly created derived service silently cannot transact until
it has its own pricing config, limit config, and a role grant. Today the
operator discovers this as a 422 (`pricing_config_missing`) or a 403-shaped
`NotAuthorised` on the first real transaction — long after creating it.

**Acceptance criteria:**
- Backend reports, per service, whether each of the three prerequisites is
  satisfied (one grouped query — no N+1 across the catalog)
- Services table shows "Not yet usable" with which piece is missing, linking to
  Pricing / Limits / Roles
- Campaign wizard warns when a base has derived services a rule doesn't cover
  — **NOT done, moved to B4.7**; the readiness work covered the config gaps,
  reward coverage is a separate question
- A derived service that IS fully configured shows no warning

**Shipped:** `ServiceOut.readiness` (three grouped queries per page) plus a
"Not yet usable · Needs …" notice in the Type column. The role check requires an
ACTIVE role, mirroring `roles.has_permission`. Deliberately reported as
"configured at all" rather than "will work": pricing/limit rows are scoped by
account_type / currency / user_type, so `false` is conclusive but `true` only
means "not obviously broken".

### Story B4.6 — Role permissions have no admin UI · Partial (2026-08-18, dd1571b)

**Description:** Found while building B4.5. `role_permissions` is one of the
three prerequisites for a service to transact, and there is no admin screen for
it anywhere — no roles page, no API client in `lib/api-endpoints.ts`. So an
operator can create a derived service in the UI but **cannot make it usable
without direct API or DB access**, which undercuts B4.2's whole point.

**Acceptance criteria:**
- Decide the smaller question first: should a derived service inherit its base's
  role grants (`has_permission` matches `transaction_type` exactly today), or
  must each grant be explicit?
- If explicit: a roles/permissions screen, and B4.5's notice links to it
- If inherited: `has_permission` resolves through `base_service_code`, with a
  test proving a derived service is permitted wherever its base is

**DECIDED: inheritance** (2026-08-18, dd1571b). A derived service falls back to
its base's grants. An explicit `permitted=false` on the variant still denies and
blocks inheritance — the only way to withhold a variant from a role holding its
base. Inheritance is one-way and tenant-scoped through the user. Readiness was
taught the same rule, plus `ROLE_ENFORCED_BASE_CODES`: only five flows call
`require_permission`, so the badge no longer demands a grant for `fund`,
`withdraw`, `merchant_cashin` or `change_pin`.

**Still open:** the roles UI itself (a permissions matrix, role CRUD, and
assignment from the user detail card). Its priority dropped once inheritance
landed and B4.8 fixed provisioning — it is now a convenience for building
customer tiers, not a prerequisite for anything. Design notes live in this
session's brainstorm; no spec written yet.

### Story B4.8 — Tenants and users ship with no role at all · Done (2026-08-18)

**Description:** Found while brainstorming B4.6, and much worse than a missing
screen. `provision_tenant_defaults` created instruments and services but NO
roles, and nothing outside the admin assign-role endpoint ever created a
`user_roles` row. Since `has_permission` denies by default (Pay-PRD-0440), every
customer in a fresh tenant was unable to send money, cash out, redeem or buy
airtime — permanently. It stayed hidden because `scripts/seed.py` hand-created a
`standard_user` role and assigned it, so dev worked while a real tenant would
not. Measured on the dev DB: 3,025 of 3,545 users held no role.

**Acceptance criteria:**
- `provision_tenant_defaults` creates default roles with grants DERIVED from
  `SERVICE_POLICY` (never a second hardcoded list), and is idempotent including
  topping up a grant added later
- Two roles, not one: `cash_in` belongs to an agent role. In a consumer role it
  is safe only because the service gate blocks consumers, so widening that
  policy would silently hand every consumer an agent capability
- `create_user` assigns the default role for the user's `user_type`; merchant
  types get none and need none (API-key flow)
- A tenant with no default roles still allows user creation (logs, never 500s)
- `scripts/seed.py` uses the same provisioning path, so dev cannot drift again
- `scripts/backfill_default_roles.py` for existing users — a script, not a
  migration, because granting money permissions should not be a side effect of
  `alembic upgrade`

### Story B4.7 — Campaign warning for uncovered derived services · Backlog

**Description:** Rewards target the RESOLVED service code (spec §8), so a rule
written against `p2p` silently does not fire for `p2p_diaspora`. Launching a
variant therefore stops its rewards until a rule is added for it.

**Acceptance criteria:**
- Campaign wizard warns when a base has derived services the rule doesn't cover
- The warning names the uncovered codes

### Story B4.3 — Step-up PIN inheritance for derived services · Backlog

**Description:** Deliberately deferred from Phase 1. `STEP_UP_TRANSACTION_TYPES`
is a fixed tuple, so a derived service is not step-up eligible. Spec §8 makes
this the one place inheritance is correct — silently *losing* a security
control is the dangerous direction — so derive the tuple from the registry plus
each derived service's base.

**Acceptance criteria:**
- A derived service of a step-up-eligible base enforces step-up
- Test proving a derived high-value transfer still demands the PIN

### Story B4.4 — Partner API contract for derived codes · Backlog

**Description:** Partner consumers reading `transaction_type` from webhooks or
reports may share the closed-set assumption. Longest lead time — it involves
other people's release cycles.

**Acceptance criteria:**
- Documented decision: version bump vs documented additive change
- Partner-facing docs describe `base_transaction_type`

---

## Epic B5 — Tenant provisioning completeness · **Backlog**

A new tenant must be fully operable from the admin UI alone. `make seed` is a
DEV script and must never be a production prerequisite. Every gap here has the
same shape: `provision_tenant_defaults` seeds part of what a tenant needs, and
`scripts/seed.py` quietly compensates for the rest — so dev works, a real
tenant does not, and nobody notices. Story B4.8 (default roles) was the first
instance found; these are the rest.

### Story B5.1 — System wallets are not provisioned for a new tenant · **Backlog · CRITICAL**

**Symptom:** A newly created tenant's System wallets page is empty. Observed on
`EcoCash Rewards` (base currency USD): "No system accounts yet — A tenant gets
its system_points_issuance + system_cash_inflow on first seed. Run make seed to
populate." Telling a production operator to run a dev seed script is not an
acceptable instruction, and the screen offers no way to create the accounts.

**Root cause:** `provision_tenant_defaults` creates instruments, services and
(since B4.8) default roles — but no system accounts. The system accounts are
instead created LAZILY by the money flows that need them
(`_get_or_create_cash_inflow` in `payments/service.py`, and the equivalents in
`rewards/service.py`), so they do not exist until a transaction has already been
attempted.

**Why this is critical, not cosmetic — there is a provisioning deadlock:**
1. Invariant #11 gives `system_cash_inflow` a no-overdraft floor, so it MUST be
   pre-funded from the bank before it can fund any user.
2. Pre-funding goes through `treasury.adjust_system_wallet`, which takes the
   target account id and raises `AccountNotFound` for an unknown target.
3. The float does not exist until `fund()` lazily creates it.

So the only route on a fresh tenant is: attempt a fund that FAILS with
`insufficient_float` (which leaves the account behind, because the get-or-create
commits separately), then create a bank mirror, then top up. That is not
discoverable, and nothing in the UI hints at it.

**Currency correctness matters here too:** the accounts must be created in the
tenant's OWN `base_currency` (USD for EcoCash Rewards, not ZAR) plus `PTS` for
points issuance — the same bug class already fixed for instruments, where the
code was once hard-coded to ZAR.

**Acceptance criteria:**
- `provision_tenant_defaults` creates `system_cash_inflow` in the tenant's
  `base_currency` and `system_points_issuance` in `PTS`
- Idempotent, and safe against the existing lazy get-or-create paths racing it
  (the `uq_accounts_system_scoped` constraint is the arbiter)
- A tenant created through `POST /api/v1/tenants` shows both accounts on the
  System wallets page immediately, with zero balances
- The empty-state copy no longer mentions `make seed`; if accounts are somehow
  absent it explains the operator action instead
- `scripts/seed.py` stops creating these itself and relies on provisioning, so
  dev cannot diverge again
- Test: provisioning a USD tenant yields a USD float, NOT ZAR
- Test: a fresh tenant can be pre-funded via `adjust_system_wallet` with no
  prior transaction attempt (the deadlock is gone)

**Not in scope:** the bank mirror (`operator_adjustment`). That carries real bank
details, so an operator creating it explicitly is correct.

### Story B5.2 — Audit provisioning for any remaining gaps · Done (2026-08-18)

**Description:** Two instances of this bug class have been found by accident
(B4.8 roles, B5.1 system wallets). Rather than wait for a third, diff what
`scripts/seed.py` creates against what `provision_tenant_defaults` creates, and
treat every difference as either a provisioning gap or an explicitly documented
dev-only convenience.

**Acceptance criteria:**
- A written table: every entity seed.py creates, and whether provisioning
  creates it, with a one-line justification for each dev-only item
- Anything a tenant genuinely needs moves into provisioning
- Ideally a test that fails when seed.py grows a new tenant-scoped entity that
  provisioning does not create — NOT done, remains open below

**Audit result (2026-08-18).** Every tenant-scoped entity seed.py creates,
against provisioning:

| Entity | seed.py | provisioning | Verdict |
|---|---|---|---|
| Instruments (base currency + PTS) | yes | yes (PTS mode-gated, e1f4caa) | covered |
| Baseline services | yes | yes | covered |
| Default roles + grants | was hand-rolled | yes (B4.8, df1194f) | fixed |
| System wallets (fiat + points) | was hand-rolled, hardcoded ZAR | yes (B5.1, decc63d) | fixed |
| Bank mirror (`operator_adjustment`) | yes ("Primary") | no — deliberate | dev-only stand-in; a mirror carries real bank details, operator creates it |
| Step-up policies | yes, one per guarded type | **no** | **GAP → B5.3** |
| Pricing + limit configs | yes | no — deliberate | correct by design: invariant #12 forbids implicit defaults; the readiness badge (B4.5) surfaces the gap |
| Redemption provider (+ its wallet) | yes (sample) | no | dev-only demo data |
| Event source + Kafka topics | yes | no | dev-only; external integrations are explicitly registered (Pay-PRD-0495) |
| Users, wallets, opening balances, campaigns | yes | no | dev-only demo data |

Other angles checked and found FINE: no remaining "seed"/dev-tooling copy in
production admin-ui screens (the three found were fixed in decc63d); lazily
created accounts other than the float are credit-side targets with no
pre-funding need (no further deadlocks); `provider_redemption_wallet` is
auto-created by `register_provider` and `airtime_merchant_holding` is
merchant-owned (both correct); roles was the only backend module with a full
CRUD API and no admin UI page (tracked in B4.6).

### Story B5.3 — Fresh tenants demand a PIN on every guarded transaction · Backlog

**Description:** Found by the B5.2 audit. `enforce_step_up` is fail-closed by
design — a MISSING policy requires a PIN at ANY amount (step_up/service.py:65)
— and provisioning creates no step-up policies; only seed.py does. So every
guarded flow on a fresh tenant demands a PIN for a R1 transfer until an
operator configures thresholds. Not broken (the Step-up PIN page exists), but a
degraded default nobody chose, and invisible until customers complain.

**Acceptance criteria:**
- Decide the default: provision an explicit high-threshold policy per guarded
  type (mirroring seed.py, which iterates STEP_UP_TRANSACTION_TYPES so new
  types are covered automatically), or keep PIN-always and say so in the UI
- Whichever is chosen, the Step-up PIN page shows the effective behaviour for
  an unconfigured type instead of implying "no policy = no PIN"

### Story B5.4 — Guard against seed/provisioning drift · Backlog

**Description:** The open remainder of B5.2. Three gaps (roles, system wallets,
step-up) all came from seed.py compensating for provisioning. A test should
fail when seed.py grows a new tenant-scoped entity that provisioning does not
create, so the next gap is caught at commit time, not in production.

---

## Epic B6 — `business_type` is not enforced outside reward paths · **Backlog**

`tenants.business_type` ('wallet' | 'rewards' | 'both') is documented as the
deployment-mode gate, and `app/shared/tenant_mode.py` calls itself its "single
reader". But it only gates reward EXECUTION. Nothing gates the surface area: not
provisioning, not the admin UI. So a tenant is shown — and can configure —
features outside what it was sold.

### Story B6.1 — A wallet-only tenant is shown the rewards product · Done (2026-08-19, e1f4caa + 18d8a65)

**Symptom:** With `Casava Fintech` (business_type `wallet`, base currency TOKEN)
as the active tenant, the admin UI shows Campaigns, Segments, Multipliers,
Budgets and Redemption in the sidebar, and `PTS` appears as a selectable
currency in configuration dropdowns (service charges, limits, pricing). None of
it is in scope for a wallet-only tenant.

**Root cause, two independent halves:**
1. `provision_tenant_defaults` creates the `PTS` points instrument
   unconditionally — `backend/app/modules/tenants/service.py:308`, whose own
   comment says "always, regardless of base_currency", justified by "the rules
   engine credits reward points to every tenant". That premise is false for a
   wallet-only tenant. The PTS instrument is what puts points into currency
   dropdowns.
2. The admin UI does no mode gating at all. `admin-ui/components/app-shell/
   sidebar.tsx` contains no reference to `business_type`, so every nav item
   renders for every tenant.

**Why critical:** an operator can build configuration that can never execute —
e.g. a PTS-denominated service charge or limit for a tenant with no points
programme — and each such row is dead config of exactly the kind invariant #12
exists to prevent. It also misrepresents the product: a wallet-only customer
sees a rewards console they have not bought, which is a live credibility problem
in demos and a support problem in production.

**Acceptance criteria:**
- Sidebar renders rewards-only sections (Campaigns, Segments, Multipliers,
  Budgets, Redemption) only when the active tenant's mode includes rewards
- `PTS` is not offered in any currency/instrument dropdown for a wallet-only
  tenant
- Provisioning creates the PTS instrument only for modes that include rewards
  ('rewards', 'both'), and the points issuance system account likewise
- Backend rejects, not just hides: creating a PTS-denominated pricing/limit/
  service-charge config for a wallet-only tenant returns 422 (a hidden dropdown
  is not enforcement — the API is reachable directly)
- Tests for a wallet tenant, a rewards tenant and a both tenant

**Shipped in two halves:** provisioning (e1f4caa — no PTS instrument or points
issuance account for wallet-only) and surface+enforcement (18d8a65 — sidebar
drops the five rewards sections via one `tenantHasRewards` predicate; the
pricing/limits/instruments dialogs take a `pointsAvailable` prop; and
`assert_points_scope_allowed` 422s `points_not_available` at config PROPOSE,
REVISE, APPLY and instrument creation). Existing dev tenants healed by
re-provisioning; Casava's pre-gate PTS instrument soft-deleted.

### Story B6.2 — The mirror case: a rewards-only tenant shows wallet features · Backlog

**Description:** Same root cause, opposite direction. A `rewards` tenant should
presumably not be offered System wallets, Fund/Withdraw, cash-in/cash-out
services or fiat service charges. Needs a product decision on exactly which
surfaces belong to each mode before implementing — B6.1 is the urgent half
because it is the one observed.

**Acceptance criteria:**
- A documented matrix: every admin UI section and every base service, mapped to
  the modes that should see it
- Gating applied from that single matrix, not per-screen guesswork

### Story B6.3 — Changing `business_type` after creation has undefined behaviour · Backlog

**Description:** The Tenants screen lets an operator edit Business type on an
existing tenant. Nothing defines what happens to data already created under the
old mode — points accounts, campaigns, rules, PTS pricing rows — when a tenant
moves 'both' → 'wallet', or what gets provisioned when it moves the other way.
Today the change is a bare column update.

**Acceptance criteria:**
- Decide and document: is a mode change permitted, and is it additive only?
- Widening (e.g. 'wallet' → 'both') provisions what the new mode needs
- Narrowing either 422s while rewards data exists, or is explicit about what
  becomes inert (and the UI says so before the operator confirms)
- Audit row captures before/after mode

---

## Epic B7 — Approvals page does not scale · **Backlog**

Found 2026-08-19 after load testing left ~2,200 money-operation rows in the dev
DB: a single visit to the unified approvals page takes tens of seconds and has
badly slowed the Playwright e2e suite.

### Story B7.1 — Server-side pagination for the maker-checker queues · Done (2026-08-19)

**Description:** `admin-ui/app/(authenticated)/approvals/page.tsx` fetches the
FULL dataset of all three maker-checker queues (config_requests,
money_operations, user_operations) with no status filter or limit on every
visit, then filters entirely client-side in
`_components/approvals-toolbar.tsx`. The backend list endpoints (e.g.
`backend/app/modules/money_operations/service.py`) already accept a `status`
param but have no `limit`/`offset`.

**Acceptance criteria:**
- Backend list endpoints for all three queues accept `limit`/`offset` (keeping
  the existing `status` param), with docstrings per the coding guidelines
- Tests for the new query params on each endpoint (happy path, bounds/422,
  tenant isolation preserved)
- The approvals page fetches a status- and limit-aware window instead of the
  full dataset
- Tab-bar counts stay correct via cheap count queries (not by fetching rows)
- The toolbar keeps its client-side facets, applied to the fetched window
- Page load on a ~2,200-row queue is interactive in low single-digit seconds
  in dev; Playwright e2e suite time recovers

**Shipped:** `limit`/`offset` (cap 500) on all three list endpoints plus a
`GET /counts` per queue (one grouped query, served through each module's
service layer; window ordering shared in `app/shared/queue_counts.py`). The
approvals page now fetches counts for every visible queue but ROWS only for
the active tab, as one status-filtered window (`?status=`, default PENDING;
`?page=` × 200, clamped to the real page count). The toolbar's status segments
and pager are real navigations fed by whole-queue counts; search/type/date stay
client-side over the fetched page (the empty state says so explicitly). The
sidebar Approvals badge — rendered on every page — switched from three full
PENDING list fetches to the counts endpoints. 24 new backend tests
(happy/bounds-422/401/403/tenant isolation × 3 queues) + lib tests.

### Story B7.2 — Bound the per-row enrichment and index the window query · Done (2026-08-19)

**Description:** Follow-ups the B7.1 review confirmed but deferred. (a) The
money/user list endpoints still run `load_reviews` per row plus per-row payload
name resolution — bounded at 200/page now, but still ~200-800 sequential
queries per approvals page load; batch them with `IN (...)` loads. (b) The new
hot query `WHERE tenant_id=? AND status=? ORDER BY created_at DESC, id DESC
LIMIT/OFFSET` is only covered by the (tenant_id, status) index, so Postgres
sorts the whole matching set per page; add a composite
(tenant_id, status, created_at DESC, id DESC) index via Alembic to all three
request tables. (c) Consider a server-side `q` search param so the approvals
search can cover the whole queue, not just the fetched page — a checker
searching a request id that is outside the window currently sees "no match",
which reads as "does not exist".

**Shipped, all three parts:**
- (a) Batched: `load_reviews_for_requests` (one `IN` query per page instead of
  one per row) in money/user routers, the money payload-name enrichment
  resolves each UNIQUE identifier once + one `resolve_user_names` + one
  accounts-`IN` query, and user-op target names resolve in one call. Pinned by
  query-count tests asserting a 6-row page costs exactly as many statements as
  a 2-row page.
- (b) Migration 0057 swaps each queue's (tenant_id, status) index for
  (tenant_id, status, created_at, id) — EXPLAIN on the 2.2k-row dev queue now
  shows a backward index scan, no sort (0.2 ms).
- (c) Server-side search: `q` on all three list AND /counts endpoints (id,
  maker sub, maker display name, operation/config_type, payload text, plus the
  subject/target user's PROFILE name — the payload stores identifiers in
  whatever format the maker typed, so the name join normalises them in SQL the
  way `normalize_identifier` does). The approvals search box is now a debounced
  `?q=` navigation covering the whole queue; segments and pager show q-scoped
  counts while searching. Proven live: typing a funded user's name found the
  one matching pending request among 2,206 rows.

**Measured before/after (2,206-row dev queue, best of 3):** old page ~9.0s
server-side / ~8,818 queries / 2,206 rows downloaded per visit; new page ~18ms
/ ~8 queries / 10 rows; browser full-load 575–711ms (~110 KB) identical across
Pending, ALL, deep pages, and search. A follow-up commit decorrelated the
name-search subqueries after the benchmark caught a 16.3s plan (now 81ms).

### Story B7.3 — Bound the remaining transaction/audit listings · Done (2026-08-19)

**Description:** A full audit (backend endpoints + admin pages) after B7.2
found the remaining unbounded or unindexed listing reads on tables that grow
for 7 years.

**Shipped:**
- Audit log: `offset` param (id tie-break ordering), a blind Previous/Next
  pager on the audit page, and migration 0058 adding
  `ix_audit_log_tenant_created` — the default view previously seq-scanned and
  top-N sorted the whole table.
- Mobile `/catalog/me/points-history` + `/me/redemption-history`: were fully
  unbounded (every ledger entry / redemption, ever); now limit (default 50,
  cap 500) + offset. `/catalog/me/summary` lifetime sums moved from Python
  row-loops into SQL `SUM`.
- Admin user-transactions: `limit` was an unvalidated plain default (a caller
  could request the full history); now `Query(ge=1, le=200)`.
- System-wallet drill-down: gained `offset`, and orders by the ledger entry's
  timestamp so the sort no longer needs every joined transaction row.

### Story B7.4 — Remaining unbounded admin reads (audit findings) · Backlog

**Description:** The rest of the B7.3 audit, deferred. (a) Reconciliation
`list_pending` / `list_manual_review` return ALL matching rows with no LIMIT
and no (tenant_id, status, created_at) index on redemptions; consumed by the
reconciliation page, redemption page, AND the dashboard attention strip —
which only needs counts. (b) The campaigns page calls `getRulePerformance`
once per rule while the purpose-built batch endpoint
`GET /rules/performance` ("one SQL round-trip") sits unwrapped in
`api-endpoints.ts`. (c) Six native config pages fetch every change request of
their type ever, then filter to open ones in JS — push `status_filter` +
`limit` down instead. (d) The users page fetches the whole PENDING +
CHANGES_REQUESTED user-op queues just to `.find()` one target's open request —
needs a targeted lookup param. (e) `event_ingestion_log` (90-day retention but
high volume) has no list endpoint yet — design it with limit/offset from day
one.

### Story B7.5 — Ledger-derived aggregates at scale · Backlog

**Description:** Every balance read is `SUM(ledger_entries)` over an account's
full 7-year history (invariant #1), and several surfaces run it in loops:
system-wallets page (per wallet — treasury accounts hold a leg of nearly every
transaction), user detail card (per account), catalog summary, and analytics
`liquidity` (whole-ledger aggregate with no time bound, twice per dashboard
load). `AccountBalanceSnapshot` exists in the models as a designed-but-unused
read optimisation. Also: `reward_events` has no created_at/tenant-reachable
index (analytics + budgets loop aggregates over it), and the system-wallet
drill-down sort would want a (account_id, created_at) ledger index — both are
measure-first decisions on hot money-path tables, same discipline as B1.9.

---

## Epic B8 — Commission wallets, parent commission & disbursement · **Backlog**

Raised 2026-08-23 by management review. Today an agent commission is paid
straight into the agent's spendable working wallet: `assemble_charges` builds a
DEBIT `commission` pool → CREDIT `financial_wallet` leg
(`cashin/service.py:318` — "commission lands on the agent's float"), flagged
`skip_receive_cap=True` so it lands regardless of the agent's max_balance
(Story 20.3). The commission is therefore spendable the instant it is earned.

**What the business wants instead:** commission accrues in a separate,
non-spendable **commission wallet** held by Retail and Business users (agents,
super-agents, merchants, head-merchants — never consumers), sits there through
the period so fraud and clawback review can happen, and is then moved into the
working wallet by an explicit, approved **disbursement run**.

> **Depends on the in-flight user-types edition** (`feature/configurable-user-types`).
> Eligibility is a *category* question — Retail and Business get a commission
> wallet, Consumers do not — and categories only exist once that branch lands.
> Do not hardcode a five-type list here; that is the exact coupling the
> user-types work is removing.

### Story B8.1 — `commission_wallet` account type, provisioned at instrument onboarding · Backlog

**Description:** A new per-(tenant, user, currency) account type holding accrued
commission. Provisioned by the instrument onboarding path that already
provisions system accounts and backfills user wallets
(`instruments/service.py:132` `_provision_system_accounts`, `:242`
`_backfill_user_accounts`), so creating a currency yields commission wallets for
every eligible user, and creating an eligible user yields one per financial
currency.

**Acceptance criteria:**
- `ACCOUNT_TYPE_COMMISSION_WALLET` added to `ACCOUNT_TYPES` and the account-type
  CHECK; distinct from the existing tenant-level `commission` **pool** account
- Eligibility is read from the user-type catalog's **category** (Retail,
  Business), never a hardcoded type list — an operator-created Business type
  gets a commission wallet with no code change
- Consumers get none, and asking for one is refused, not silently created
- Provisioned on: instrument create (backfill for existing eligible users),
  user create, and user type-change into an eligible category
- Financial currencies only — a PTS instrument provisions no commission wallet
- Idempotent, tenant-scoped, and safe against the lazy get-or-create paths
  racing it (same discipline as B5.1)
- NOT a `financial_wallet`, so the balance guard skips it — no overdraft floor
  and no `max_balance` ceiling, matching pool/collection semantics (invariant #11)
- `scripts/backfill_commission_wallets.py` for existing eligible users — a
  script, not a migration (B4.8 precedent)
- Visible on the admin user detail card as a separate balance
- Tests: consumer → none; agent → one per financial currency; operator-created
  Business type → one; PTS → none; re-provisioning is a no-op

### Story B8.2 — Commission credits land in the commission wallet, not the working wallet · Backlog

**Description:** Retarget the commission credit leg from the earner's
`financial_wallet` to their `commission_wallet`, on every path that pays
commission.

**Acceptance criteria:**
- The charge assembler credits the earner's commission wallet; the DEBIT side
  (the tenant `commission` pool) and the `tax_commission_collected` leg are
  unchanged
- Every commission-paying path is covered (cash-in today; cash-out, airtime and
  partner flows as configured) — no path keeps the old target
- **Fails closed:** an earner with no commission wallet → 422 before any ledger
  write, never a silent fallback to the working wallet (invariant #12 discipline)
- Accrued commission is excluded from spendable balance everywhere: money-path
  available-balance reads, limits, admin user detail, mobile balance cards
- The ledger stays balanced and append-only; `skip_receive_cap` is no longer
  needed on this leg once the target is unguarded (confirm and remove)
- Commission already paid into working wallets stays there — the ledger is
  append-only. Document it; do not migrate
- Tests: a cash-in pays commission to the commission wallet; the agent's
  spendable balance is unchanged by it; a consumer-acting path pays none

### Story B8.3 — Parent commission in the commission configuration · Backlog

**Description:** A commission config can additionally pay the earner's **parent**
— an agent's transaction also compensates their super-agent. This is the
"commission hierarchy roll-up across the parent chain" explicitly deferred from
Pricing v2 (`specs/2026-07-12-pricing-v2-design.md` §Phase 2, decision D4 —
"v1 = commission to the acting agent only"). `users.parent_user_id` already
exists; nothing reads it for commission today.

**Acceptance criteria:**
- `commission_configs` gains parent commission terms (fixed / variable pct /
  cap), resolved with the same precedence and band logic as the child terms
- Resolution walks **exactly one level** via `users.parent_user_id` — never a
  chain — consistent with the two-level cap locked as user-types D7
- Retail (agent → super-agent) is the required case. Business (merchant →
  head-merchant) is a **product decision to record explicitly**, not an
  assumption
- The parent leg credits the PARENT's commission wallet (B8.1), so it inherits
  the hold-and-disburse treatment
- Both legs are funded from the tenant `commission` pool, which stays unguarded
  and may run negative — the operator tops it up
- No parent, parent in an ineligible category, or parent without a commission
  wallet → the child commission still pays; the parent leg is skipped and the
  reason recorded on the transaction (fail-open on the parent leg only —
  decision to confirm)
- Parent == acting user is impossible by construction; assert it anyway
- Admin UI: parent commission fields in the commission-config dialog, routed
  through config maker-checker like every other money config
- Tests: precedence matrix incl. parent terms; one level only; skip paths; a
  balanced ledger with three commission legs (child, parent, tax)

### Story B8.4 — Commission disbursement module · Backlog

**Description:** The point of holding commission is the review window. A new
module calculates what each eligible user accrued over a period, lets an
operator review and hold anything suspicious, and then moves the approved
amounts from commission wallets into working wallets. An agent cannot transact
against commission until this runs.

**Acceptance criteria:**
- **Two phases, separated:** (a) a *collection / statement* run computing
  per-user accrued commission for a period, with a drill-down to the
  contributing transactions; (b) a *disbursement* posting
  `commission_wallet` → `financial_wallet` per included user
- Accrual totals reconcile exactly to the ledger — the statement is derived,
  never a second source of truth
- Per-user **hold / exclude / partial disburse** with a mandatory reason
  (the fraud-review outcome), audited
- A disbursement run is bulk money movement, so it goes through **maker-checker**
  (N-eyes, mirroring treasury Epic 18) — proposed, approved, then applied
- Idempotent per (tenant, period, user): a re-run never double-pays, and the
  apply at quorum is idempotent
- The credit into the working wallet is cap-exempt (an earned payout, same rule
  as commission today)
- Clawback: an accrual can be reversed before disbursement; after disbursement
  it is a new append-only reversal, never an UPDATE
- Fails closed on missing config; tenant-isolated
- Admin UI: a disbursement-run screen — period picker, per-user table with
  accrued totals, hold/exclude affordances, run totals, and the approval flow
- Every action audited; the statement is exportable
- Tests: totals reconcile; a held user is excluded and their balance stays in
  the commission wallet; re-run is a no-op; tenant isolation; ledger invariants

### Story B8.5 — `user_type` CHECK constraints block operator-created types on every money config · **Backlog · blocks the in-flight user-types edition**

**Description:** Found while grounding B8.3. The five hardcoded user-type strings
are pinned by a CHECK constraint in **four** more places besides `users`:

| Constraint | Table |
|---|---|
| `ck_commission_configs_user_type` | `commission_configs` (`models/commissions.py:56`) |
| `ck_pricing_configs_user_type` | `pricing_configs` (`models/pricing.py:57`) |
| (limits) | `limit_configs` (`models/limits.py:52`) |
| (wallet limits) | `wallet_limit_configs` (`models/limits.py:109`) |

Migration `20260823_0061_configurable_user_types.py` drops only
`ck_users_user_type`. So on that branch as written, an operator can create a
user type and assign users to it — and then cannot give it a pricing config, a
limit config, or a commission config, because every insert violates a CHECK.
Invariant #12 then makes the new type **unusable on every money path**, failing
closed with `pricing_config_missing`. The feature ships looking complete and is
inert for its actual purpose.

The user-types design's grounding table lists `pricing_configs.user_type` and
`commission_configs.user_type` only under the precedence pattern
(`specs/2026-08-23-configurable-user-types-design.md:35`) and does not mention
these constraints.

**Acceptance criteria:**
- All four CHECKs dropped in the same migration that drops `ck_users_user_type`,
  so no intermediate state exists where a type is creatable but unconfigurable
- Validation moves to the service layer, resolved against the tenant's own
  active types (the same `assert_user_type_valid` the identity path uses)
- A config row referencing a retired type still resolves — retirement must never
  silently reprice (user-types D3, spec §11)
- Test: create a type → create a pricing, limit and commission config for it →
  transact end to end
- **Should be pulled into `feature/configurable-user-types` rather than
  shipped after it**

---

## Epic B9 — Use-case-scoped ledger locking · **Backlog**

Raised 2026-08-23. Invariant #11 funnels every money path through
`post_transaction`, where `_enforce_balance_guard` (`ledger/service.py:360`)
takes a `FOR UPDATE` on every guarded leg. That centralisation is correct and
must stay. What is **not** use-case-aware is which legs get locked: the guard
locks any account whose type is in `_OVERDRAFT_GUARDED_ACCOUNT_TYPES` and whose
net delta is non-zero, *before* it knows whether any check will actually read
the balance. Two distinct costs follow.

> **Scope discipline:** this epic narrows *where a lock is taken*. It must not
> weaken any check that actually runs — the M-01 check-then-act race is exactly
> why the guard exists. Every debit keeps its lock unconditionally.

### Story B9.1 — Do not lock a leg that no check will read · Backlog

**Description:** For a pure **credit** leg the guard skips the cap check when
`is_reversal` or `skip_receive_cap` is set (`ledger/service.py:443`) — but
the lock was already acquired at `:424`, and `derive_balance` at `:429` still
runs a full `SUM(ledger_entries)` whose result is then discarded. So a reversal,
a refund and an agent commission credit each take a row lock held through commit
and pay for a full-history aggregate to decide nothing.

**Acceptance criteria:**
- A leg is locked only when a check will read it: every **debit** always; a
  **credit** only when the cap check will actually run (not a reversal, not
  `skip_receive_cap`, and a cap resolves for the owner)
- `derive_balance` is not called for a leg whose check is skipped
- Canonical account-id lock ordering is preserved across the locks that remain,
  so no new deadlock order is introduced
- **CLAUDE.md invariant #11 is updated in the same change** — the invariant text
  currently describes the unconditional form
- `.claude/rules/ledger-invariants.md` updated likewise
- Concurrency test proving the removed lock cannot admit an over-cap credit:
  two concurrent capped credits still resolve to one success, one 409
- Before/after measurement on a commission credit and a reversal

### Story B9.2 — Shared operator accounts serialise the whole tenant · **Backlog · the redemption hotspot**

**Description:** Raised directly from the redemption case. The
`cashback_provider_wallet` that funds points-to-cash payouts is **one row per
(tenant, currency)** (`models/accounts.py:62-68`) and it is in
`_OVERDRAFT_GUARDED_ACCOUNT_TYPES`, so every internal redemption in the tenant
takes `FOR UPDATE` on that same row and holds it **through commit**. Redemptions
therefore do not run concurrently — they queue, tenant-wide, behind one lock,
and the queue lengthens with redemption volume, which is exactly the volume a
rewards programme is designed to produce.

`system_cash_inflow` has the identical shape for the funding side: every
cash-in, top-up and partner fund locks the single float row.

Unlike B9.1 this lock **cannot simply be dropped** — both accounts carry a real
no-negative floor (`InsufficientCashbackFunds`, `InsufficientFloat`) and the
check is genuine. The fix is a contention strategy, not a removal.

**Acceptance criteria:**
- Measure the current ceiling first: concurrent redemptions per second per
  tenant against the single wallet, and the same for the float on cash-in
  (dev load testing has already shown a ~15 TPS ceiling — establish how much of
  it is this lock)
- A documented decision / ADR choosing the strategy, with the rejected options
  recorded: sharded sub-accounts with a routing rule; pre-authorised balance
  tranches; a reservation counter checked before the ledger write; or an
  authoritative denormalised balance column
- **Cross-reference Epic 11.1** (live balance columns on accounts) — decide
  explicitly whether that work supersedes this one or composes with it, rather
  than building two answers to the same question
- The no-negative floor is preserved exactly: no strategy may permit the pool to
  go negative, and the failure mode stays a distinct 409
- Concurrency test at the target rate showing no lost update and no negative
  balance
- Applies to `cashback_provider_wallet` and `system_cash_inflow`; the tenant
  `commission` pool joins the list if B8 ever makes it guarded

### Story B9.3 — A written lock policy per account type · Backlog

**Description:** The guard's behaviour is currently inferable only by reading
`_enforce_balance_guard` end to end, and every new account type inherits the
guard implicitly — B8.1 adds `commission_wallet`, and B4's derived services
already showed how easily a new code inherits the wrong default. Write the
policy down as a table so the next account type is a deliberate decision.

**Acceptance criteria:**
- One table: account type × leg direction × which checks run × locked or not ×
  why — covering every member of `ACCOUNT_TYPES`
- Lives in `.claude/rules/ledger-invariants.md`, referenced from CLAUDE.md
  invariant #11
- A test asserting the table and `_OVERDRAFT_GUARDED_ACCOUNT_TYPES` agree, so a
  new account type cannot be added without classifying it

---

## Epic B10 — TPS monitoring & load-aware bulk execution · **Backlog**

Raised 2026-08-26. The platform has no load signal: nothing reports requests or
transactions per second, `/metrics` exists only as a Phase 2 intention in
`.claude/rules/observability.md`, and there is no history to answer "what was
the platform doing at 02:00 last Tuesday?".

That gap becomes a live risk with B8. Bulk commission disbursement and bulk
withdrawal (B8.6) post thousands of rows through `post_transaction`, which takes
`FOR UPDATE` row locks on the wallet legs and the operator float (invariant
#11). A 5,000-row batch launched at 09:00 on payday competes with live traffic
for the same connection pool and the same locks — and dev load testing already
puts the P2P money path at a ~14–15 TPS plateau that *degrades* to ~12 TPS at
concurrency 50 (see also B9.2, which measures how much of that ceiling is the
single-row float lock).

**Design:** `docs/superpowers/specs/2026-08-26-tps-monitoring-design.md`.
Decisions locked there: TPS counts all state-mutating API writes (not just money
paths); both global and per-tenant scopes are recorded and the bulk gate reads
**global**, because the pool and the locks are shared across tenants; Redis is
the counter of record with Prometheus and Postgres both deriving from it; a
blocked batch retries indefinitely rather than expiring.

> **Stories B10.1–B10.4 have no dependency on B8** and can land while it is
> still in review. Only B10.5 needs the `commission_batches` runner to exist.

### Story B10.1 — TPS counter, write middleware, and 30-second history · Backlog

**Description:** The measurement substrate. Redis per-second buckets
(`tps:{scope}:{unix_second}`, TTL 180s) incremented by a FastAPI middleware on
every state-mutating request and by bulk workers per posted row, plus a
`tps_samples` table written by a Celery-beat sampler every 30 seconds.

**Acceptance criteria:**
- Middleware counts `POST/PUT/PATCH/DELETE` that reached a route handler;
  excludes `GET/HEAD/OPTIONS`, `/healthz`, `/metrics`, `/`, and `401/403/404/405/429`
- `409` and `5xx` **are** counted — a replay and a failure both consumed a pool
  slot, and excluding failures would make the meter read quiet during an incident
- Counted after `call_next`, so the tenant (resolved by an auth dependency onto
  `request.state`) and the status code are both known
- Redis failure on the write path is swallowed and never fails a request
  (surfaced as `sasai_tps_counter_errors_total`); failure on the read path raises
  so the gate can fail closed
- Rolling read excludes the current partial second, and returns `peak_second`
  alongside the mean — a 30s average of 20 can hide a one-second burst of 200
- One pipeline, one round-trip on the hot path; ~0.2–0.3 ms budget
- `tps_samples` with **two partial unique indexes** on `bucket_start` (one
  `WHERE tenant_id IS NULL`, one `WHERE NOT NULL`) — a plain composite unique
  will not dedupe the global rows, since Postgres treats NULLs as distinct
- Sampler derives its bucket from the clock (aligned to absolute 30s
  boundaries), not from when beat fired, and upserts `ON CONFLICT DO NOTHING`
- Tenants with no writes in a window get no row; the read path zero-fills
- Daily pruner enforces 7-day retention
- Tests: partial-second exclusion, idempotent double-fire producing one global
  **and** one per-tenant row, swallowed write error, raising read error

### Story B10.2 — `/metrics` Prometheus exposition · Backlog

**Description:** A custom `prometheus_client` collector that derives all
families from Redis at scrape time, on a dedicated registry.

**Acceptance criteria:**
- New dependency `prometheus-client>=0.21.0`; `prometheus` service added to
  `sasai-wallet-infra/docker-compose.yml` scraping every 15s
- Bearer-token gated via `settings.METRICS_TOKEN`; required outside local dev
- **No default process collectors** on the registry — they are per-uvicorn-worker
  and actively misleading behind a load balancer. Excluding them is what makes
  any instance a valid scrape target
- Nothing held in process memory, so two API instances backed by one Redis
  return identical values (asserted by test)
- Families: `sasai_write_ops_total{source}`, `sasai_tenant_write_ops_total{tenant_id}`,
  `sasai_tps_current{scope,tenant_id}`, `sasai_tps_peak_second`,
  `sasai_bulk_gate_open{tenant_id}`, `sasai_bulk_batches{state}`,
  `sasai_bulk_batch_oldest_queued_seconds`, `sasai_bulk_gate_pauses_total{reason}`,
  `sasai_tps_counter_errors_total`
- Postgres-backed gauges cached 15s inside the collector so a tight scrape
  interval cannot make `/metrics` a load source of its own
- Commented `alerts.yml` shipped (sustained-high TPS, batch starving >6h,
  counter blind) — rules only, no receiver wired
- `http_request_duration_seconds` and the rest of the observability-rules metric
  set are explicitly **out of scope**; this story adds the endpoint, not the
  full metric catalogue

### Story B10.3 — `platform_settings` table and per-tenant bulk window · Backlog

**Description:** Somewhere to put a platform-scoped threshold, and a per-tenant
off-hours window. No platform-scoped config table exists today — every config
table carries `tenant_id`.

**Acceptance criteria:**
- `platform_settings` KV table with **no** `tenant_id`, a typed key registry in
  code (unknown key → 422, so it cannot become a dumping ground), and every
  write audit-logged
- Resolution order: `platform_settings` row → `settings.py` → hard-coded default,
  so env seeds the system and stays the DR fallback
- Redis-cached 30s (the gate reads thresholds per chunk and must not add a
  Postgres round-trip); a write busts the cache immediately
- **No maker-checker** — these are operational knobs, and `config_change_requests`
  is tenant-scoped and band-shaped. Record the decision; it becomes a ninth
  config type if the business later wants four eyes on a threshold
- `tenants` gains `bulk_window_tz` / `bulk_window_start` / `bulk_window_end`, all
  nullable; all-NULL falls back to the platform default, partially-set is 422
  `bulk_window_incomplete`, `start == end` means always open
- Window arithmetic handles midnight wrap (22:00→04:00) and DST without
  special-casing; `tzdata` installed explicitly in the Dockerfile so a base-image
  change cannot silently move everyone's window
- Edited on the Tenants page, audit-logged — **not** via config maker-checker,
  for the reason above
- Startup validator rejects `BULK_TPS_RESUME_AT >= BULK_TPS_PAUSE_AT`; inverting
  them silently disables the hysteresis B10.5 depends on

### Story B10.4 — Dashboard TPS panel · Backlog

**Description:** Current TPS plus one hour of history (120 points at 30s) on the
admin dashboard.

**Acceptance criteria:**
- `GET /api/v1/analytics/tps?tenant_id=&window=1h` on the existing analytics
  router, reusing `_require_finance_or_admin`
- **`platform-admin` sees the global series; a tenant operator does not** — the
  global number is cross-tenant information. Every role gets the derived
  `status` chip (quiet/normal/busy), so a tenant operator learns why their batch
  is waiting without learning how busy anyone else is
- Response carries current, thresholds, the tenant's bulk window with
  `open_now`, and 120 zero-filled history points
- `window` accepts `1h` only; the parameter exists so `6h`/`24h` are additive
  later, anything else 422
- Panel placed with the operational surfaces near the attention strip, **not**
  among the money KPI tiles — TPS is not a business metric
- Drawn on the existing `chart-geometry.ts` + `plot-frame.tsx` frame: fixed
  `VB_WIDTH=1000` viewBox, `preserveAspectRatio="none"`, therefore
  `vectorEffect="non-scaling-stroke"` on every stroke and all text as
  absolutely-positioned HTML overlays (`<text>` distorts under the stretch)
- Two horizontal threshold rules and a shaded bulk-window band, so headroom and
  the next window are visible rather than inferred
- Polls every 30s, aligned to the sample cadence
- Batch list renders `PAUSED` with its reason and `next_attempt_at` in plain
  language, so a waiting batch never looks stuck

### Story B10.5 — TPS-aware bulk admission gate · Backlog · **depends on B8.6**

**Description:** Make the `commission_batches` runner refuse to run when the
platform is busy or the window is shut, re-checked before every chunk.

**Acceptance criteria:**
- `check_bulk_admission` ANDs window-open with a global-TPS check, evaluated
  window-first (free, and a shut window makes the Redis read pointless)
- **Hysteresis:** start/resume requires TPS < `BULK_TPS_RESUME_AT` (25), while a
  running batch continues until TPS ≥ `BULK_TPS_PAUSE_AT` (40). Without the band
  a batch that counts its own rows pauses itself, sees the number fall, resumes,
  and thrashes
- Bulk rows **do** count toward TPS, tagged `source="bulk"` — otherwise two
  concurrent batches are invisible to each other
- Redis unreachable → refuse with `load_unknown`. Running a bulk batch blind is
  worse than delaying it
- `BULK_SELF_TPS_CEILING` (20 rows/s) paces the runner independently of the
  gate, so a wrong measurement or a bad threshold still cannot exceed a known rate
- Chunk size 50 bounds the over-run past a spike to ~2.5s against the 30s window
- Lifecycle gains `QUEUED`, `RUNNING`, `PAUSED`; terminal states unchanged —
  **the gate never terminates a batch**
- Retries indefinitely (`max_retries=None`), backoff 60s doubling to 900s, reset
  on a successful chunk. Window-closed `retry_after` is capped so a batch
  approved at noon wakes periodically rather than sleeping 13 hours in one retry
  a worker restart would lose
- Starvation is handled by **visibility, not expiry**: `queued_at` →
  `sasai_bulk_batch_oldest_queued_seconds`, alert at 6h, attention-strip entry
- Resumption posts nothing twice — `commission_batch_rows.status` stays
  authoritative and per-row idempotency keys absorb any overlap (invariant #2).
  `rows_posted` is display-only progress
- `gate_pause_count` per batch recorded as the threshold-tuning signal
- Tests: spike mid-run → PAUSED + retry; drop → resumes and completes with no
  double-post; worker killed mid-chunk → posted rows skipped; approved outside
  the window → never enters RUNNING; the §7.3 hysteresis table asserted directly

### Story B10.6 — Baseline the thresholds against real capacity · Backlog

**Description:** The shipped defaults (40 pause / 25 resume) are **placeholders,
not measurements**. The dev stack tops out around 15 TPS on the money path, so
at those defaults the gate never closes locally and the feature looks like it
works by doing nothing.

**Acceptance criteria:**
- `.env.example` ships `BULK_TPS_PAUSE_AT=8` / `BULK_TPS_RESUME_AT=5` with a
  comment explaining why, and the seed sets a narrow bulk window on the dev
  tenant, so the gate is actually exercised in dev
- A multi-worker, sized-pool capacity measurement (not `make dev` — see the
  load-testing notes in `scripts/.claude.md`), producing the real write-path
  ceiling
- Thresholds re-derived from that measurement and from `tps_samples` history
  across at least one month-end, and written into `platform_settings`
- Explicit decision recorded on whether the all-writes metric (a config write
  weighs the same as a ledger post) is too coarse in practice; the `source`
  label already partitions the counter if a weighted variant is needed
- Cross-reference **B9.2** — if the float/cashback lock is the real ceiling,
  raising it changes these numbers

---

## Epic B11 — Commission approval drawer hides the money terms it approves · **Backlog**

Raised 2026-08-27 from the Commission approvals screen. The commission-wallet
edition added four money-affecting fields to `commission_configs`
(`payout_destination`, `parent_fixed_commission`,
`parent_variable_commission_pct`, `parent_commission_cap`). The CREATE dialog
writes all four and the backend stores and applies all four — but the
maker-checker REVIEW drawer renders none of them.

`admin-ui/app/(authenticated)/_components/config-detail.tsx` builds the band
table from exactly three keys per band (`:131-133`):

```ts
fixedKey: isPricing ? "fixed_fee" : "fixed_commission",
varKey:   isPricing ? "variable_fee_pct" : "variable_commission_pct",
capKey:   isPricing ? "fee_cap" : "commission_cap",
```

so the drawer shows BAND / FIXED / VARIABLE % / CAP and stops. A checker
approving a commission schedule therefore cannot see **where the commission
pays** (spendable main wallet vs held commission wallet) or **what the
supervisor earns** — both of which move real money, and the parent rate is a
value spec D8 deliberately forces the maker to state explicitly.

This is a maker-checker integrity gap, not cosmetics: four-eyes means the second
pair of eyes can actually see what it is signing off.

### Story B11.1 — Show destination + parent commission in the review drawer · Backlog

**Description:** Render the four fields in `config-detail.tsx` for
`config_type = "commission"`, and make sure the same values appear in the
before/after diff a checker reads on an UPDATE.

**Acceptance criteria:**
- The drawer shows the payout destination for a commission request, worded as
  the operator picked it ("Main wallet" / "Commission wallet"), not the raw key
- The band table gains parent fixed / parent variable % / parent cap columns, or
  the parent terms render as their own labelled block — parent terms are
  scope-level in the create dialog even though they are stored per band, so the
  layout should not imply they can differ between bands
- `config-compare.tsx` diffs the four fields on an UPDATE, so a checker sees a
  changed parent rate highlighted the way a changed fee already is
- A zero parent rate renders as an explicit "0", never a blank — D8's whole
  point is that zero is a stated decision, and a blank cell would erase the
  distinction between "stated zero" and "not set"
- Frontend test: a commission request payload carrying all four fields renders
  them; a legacy payload backfilled by migration 0069 renders explicit zeros
- E2E: propose a commission rule with a non-zero parent rate, open it in the
  Configuration approvals queue, and assert the parent rate is on screen before
  the Approve button is pressed

**Related:** the same drawer is shared with pricing, which has no parent concept
— gate the new columns on `config_type` rather than widening the shared band
table for everyone.

---

## Epic B12 — The agent hierarchy is invisible from both ends · **Backlog**

Raised 2026-08-27 from the Users screen. `users.parent_user_id` drives who a
supervisor is, and since the commission-wallet edition it also decides **who
gets paid parent commission**. An operator cannot see that relationship from
either direction.

Verified against the dev database, not inferred: the agent on `+27655555556`
**does** carry `parent_user_id = aa937b1e-…` pointing at a live `super_agent`,
and `get_user_detail` returns both `parent_user_id` and `parent_name`. The data
is correct and the API serves it. Only the UI is at fault.

### Story B12.1 — "Reports to" is rendered in the Address tab · Backlog

**Description:** `user-detail-card.tsx:320-326` renders the supervisor inside
the **"Address & country"** tab:

```tsx
{detail.parent_user_id ? (
  <p …>Reports to <span className="font-mono">{detail.parent_name ?? shortId(…)}</span></p>
) : null}
```

A supervisor is identity, not an address. Nobody opens "Address & country" — a
tab whose only other content is "No address on file" — to find out who an agent
reports to, so the relationship reads as absent even when it is set.

The backend already intended otherwise: the `parent_name` field's own docstring
says it exists "so the UI shows 'Reports to: <name>' instead of a bare id".

**Acceptance criteria:**
- The supervisor renders on the identity header, beside the user-type badge,
  where the type and status already are — not inside a content tab
- It is a link to the supervisor's own user page; an operator reconciling
  commission needs to get there in one click
- Absent supervisor renders nothing at all (no empty "Reports to —"): most
  users legitimately have none and a blank label would read as a defect
- A supervisor whose name does not resolve still renders, falling back to the
  short id as it does today
- Frontend test: a detail payload with `parent_name` renders it on the header;
  one without renders no supervisor element

### Story B12.2 — A supervisor cannot see who reports to them · Backlog

**Description:** There is no children / downline surface anywhere — no endpoint
and no UI. Opening a `super_agent` shows nothing about the agents beneath them.

Unlike B12.1 this was never specified. The configurable-user-types spec
(`specs/2026-08-23-configurable-user-types-design.md`) deferred *attaching or
changing* a supervisor after onboarding (§7.5, and again in its out-of-scope
list) but never covered *displaying* the downline in either direction.

It matters more now than it did then: parent commission pays a supervisor off
this hierarchy, so an operator reconciling a commission run — or investigating a
disbursement — has no way to answer "which agents feed this super-agent's
commission?" except by querying the database.

**Acceptance criteria:**
- A hierarchy-bearing user's detail page lists the users whose
  `parent_user_id` points at them: name, type, status, and their own link
- Only rendered for a type in a category that supports hierarchy — a consumer
  can never have children and should not show an empty panel
- Paginated, and tenant-scoped like every other user query (NFR-0220)
- Backend test: a super-agent with three agents lists exactly those three; a
  cross-tenant child never appears
- Reconciliation view: the list carries each child's accrued commission
  contribution, or explicitly does not and says why — decide deliberately rather
  than shipping a bare name list that stops one question short

**Related:** §7.5 of the user-types spec still owns the harder question it
deferred — whether re-parenting a live agent changes commission attribution on
historical transactions. Displaying the hierarchy does not require answering
that; changing it does.

---

## Epic B13 — A statement row does not say which wallet moved · **Backlog**

Raised 2026-08-27 from the user Transactions tab. A user now holds **two**
wallets per financial currency — a spendable main wallet and a held commission
wallet — but a statement row carries only `currency`. So "+ZAR 100.00 · IN"
does not say whether that money is spendable or sitting held awaiting a
disbursement run.

That is the one distinction the commission-wallet edition exists to make, and
the statement erases it.

The data is already in hand. `_build_recent_txns_payload` computes
`user_entry` — the ledger leg on one of the caller's own accounts — to derive
`direction`, and since the counterparty work it also builds
`own_label_by_account`, mapping every one of the user's accounts to a label.
Neither reaches the response.

### Story B13.1 — Add the wallet the movement touched · Backlog

**Description:** Surface the caller's own side of the ledger on each row, so an
operator can tell a commission accrual from a cash-in at a glance.

**Acceptance criteria:**
- Each row names the caller's wallet ("Main wallet" / "Commission wallet"),
  sourced from the ledger leg, not inferred from `transaction_type` — inferring
  it would rebuild the per-type map that B11 and the counterparty fix both
  removed
- The admin Transactions table shows it as its own column; `currency` stays
  separate, because a user can hold the same currency in both wallets
- Present on the mobile `/me/wallet` feed too — the payload is shared, and a
  customer has the same question about their own money
- Backend test: a commission accrual row names the commission wallet, a cash-in
  names the main wallet, and neither is derived from the transaction type

### Story B13.2 — `direction` is arbitrary when the user owns both legs · Backlog

**Description:** A correctness bug, not a display gap, and newly reachable
because the commission wallet made **same-user two-leg** transactions ordinary.
Commission disbursement is the obvious case, but an everyday cash-in is one too
— see B13.3, where the acting agent holds both a `financial_wallet` DEBIT and a
`commission_wallet` CREDIT in the same transaction.

`identity/service.py:1431` picks the caller's leg with:

```python
user_entry = next((e for e in entries if e.account_id in own_account_set), None)
direction = "in" if user_entry.entry_type == "CREDIT" else "out"
```

Before commission wallets a user owned exactly one leg of any transaction, so
`next()` was unambiguous. That is no longer true — both a disbursement and a
commission-earning cash-in give the user two legs — so `direction` is decided by
whichever leg the query happened to return first. Entry order is not guaranteed,
so the same transaction can legitimately render IN or OUT on different loads.

**Acceptance criteria:**
- Direction for a same-user movement is chosen deliberately, not by enumeration
  order. Options to decide between, explicitly: render it as a single
  "transfer" row naming both wallets (from → to), or render the leg matching the
  wallet the row is filtered to
- The existing single-leg behaviour is unchanged — this must not perturb p2p,
  cash-in, cash-out or funds
- Backend test: a commission disbursement renders the SAME direction across
  repeated loads, and the assertion does not depend on ledger entry ordering
- If the "transfer" shape is chosen, the currency filter still works: both legs
  share a currency, so the row must not appear twice under one filter

**Related:** B13.1 supplies the wallet label this needs. Doing B13.1 alone
would leave a row that names a wallet while its direction was picked at random.

### Story B13.3 — An earned commission never appears on the statement · Backlog

**Description:** Reported 2026-08-27 against a real cash-in. **The money path is
correct** — verified leg by leg on transaction `S_20260827164212020448`:

```
DEBIT  102.3858  financial_wallet          AGENT      (principal + fee + tax)
CREDIT 100.0000  financial_wallet          customer
CREDIT   2.0000  system_fee_collected      SYSTEM
CREDIT   0.3858  tax_service_collected     SYSTEM
DEBIT    5.7500  commission                SYSTEM
CREDIT   5.0000  commission_wallet         AGENT      <- earned, invisible
CREDIT   0.7500  tax_commission_collected  SYSTEM
DEBIT    0.5750  commission                SYSTEM
CREDIT   0.5000  commission_wallet         super-agent <- earned, invisible
CREDIT   0.0750  tax_commission_collected  SYSTEM
```

The agent earned R5.00 and their super-agent R0.50, both credited to the right
commission wallets, both taxed, and the whole transaction balances. The
statement shows a single row — "Cash In · OUT · −ZAR 100.00" — and the
commission leg is nowhere.

Cause is B13.2's: the row is built from ONE of the caller's legs
(`user_entry = next(...)`), and the acting agent holds two here — the
`financial_wallet` debit they paid, and the `commission_wallet` credit they
earned. Whichever is enumerated first wins and the other vanishes.

`transactions.commission_amount` is populated (5.000000) and the payload carries
it, but the admin table renders only SERVICE CHARGE, so even the display-only
figure never reaches the screen.

**Acceptance criteria:**
- A transaction that credits the caller's commission wallet surfaces that
  movement — as its own row, or as a row that reports both of the caller's legs.
  Decide which deliberately; a cash-in that shows only the debit reads as though
  the agent worked for nothing
- The super-agent's statement shows the parent commission they earned, on the
  same terms. Today their downline's cash-in produces a leg into their
  commission wallet that appears on no screen at all
- A **wallet filter** on the Transactions tab — All / Main wallet / Commission
  wallet — so an operator can read the two apart. This is what B13.1's wallet
  column is for; the filter is the natural second half
- The filter is **absent** for a user whose category cannot hold a commission
  wallet: a consumer has no commission and must not be shown an empty toggle
  implying they do
- Commission columns render only for the party the commission actually affected,
  preserving the existing per-party perspective rule — a customer must not see
  the agent's earnings on their own copy of the transaction
- Backend test: after a cash-in with a non-zero commission, the ACTING agent's
  statement reports the commission-wallet credit, the SUPER-AGENT's reports the
  parent credit, and the CUSTOMER's reports neither

**Related:** B13.1 (wallet column) and B13.2 (direction) are prerequisites —
this story is the reason all three exist, and shipping it alone would surface a
commission row whose direction is still decided by ledger ordering.

---

## Epic B14 — A supervisor's statement misstates what they received · **Backlog**

Raised 2026-08-27 from a super-agent's Transactions tab. Two defects on the same
row, one of them a **financial misstatement on an operator-facing screen**.

### Story B14.1 — AMOUNT shows the transaction's headline, not the viewer's movement · Backlog

**Description:** The row reports `transactions.amount` — the headline principal —
rather than the ledger movement on the *viewer's own* account. Verified against
the two rows on the reported screen:

| Reference | Statement shows | Super-agent's actual leg |
|---|---|---|
| `S_20260827164802020449` | **+ZAR 200.00 IN** | CREDIT **1.000000** commission_wallet |
| `S_20260827164212020448` | **+ZAR 100.00 IN** | CREDIT **0.500000** commission_wallet |

A supervisor who earned R0.50 is shown "+ZAR 100.00 IN" — overstated **200×**,
with an IN direction that makes it read as money received. Nothing on the screen
contradicts it.

Cause is `identity/service.py`, which emits `"amount": str(t.amount)` verbatim.
For every party that existed before parent commission this coincided with their
own leg — a p2p sender moves the headline, a cash-in customer receives it — so
the shortcut was invisible. A parent-commission earner is the first party whose
leg is a small fraction of the headline, and the shortcut becomes a lie.

**This is the most severe of B11-B14. Treat it as a correctness defect on a
money surface, not a display polish item.**

**Acceptance criteria:**
- The amount reported is the NET movement on the viewer's own account(s) for
  that transaction, derived from the ledger, signed to match `direction`
- The transaction's headline principal may still be shown, but must be a
  SEPARATE, clearly-labelled figure — never the number in the amount column
- A parent-commission row on a supervisor's statement reports their actual
  credit (R0.50), not the principal (R100.00)
- Existing single-leg parties are unchanged: a p2p sender, a cash-in customer
  and a funded user all still see the same figures they see today
- Backend test asserting the supervisor case explicitly, with a headline
  deliberately orders of magnitude larger than the commission, so a regression
  that reverts to `t.amount` cannot pass
- Audit the same substitution wherever else a transaction's headline stands in
  for a party's movement — the mobile `/me/wallet` feed shares this payload

### Story B14.2 — COUNTERPARTY cannot express a transaction the viewer is not party to · Backlog

**Description:** Reported as "the counterparty is not understandable". On a
super-agent's statement a downline cash-in shows counterparty "Agent Normal",
which says nothing about what happened: the agent paid, Alice received, and the
super-agent merely earned from it.

A single counterparty field assumes the viewer is one of the two sides. For
parent commission that assumption breaks — the supervisor is a third party to a
transaction between two other people.

**Acceptance criteria:**
- A transaction the viewer is not a principal party to reports **sender** and
  **receiver** rather than a single counterparty, so a supervisor reads "Agent
  Normal → Alicia Mokoena" and understands it
- Where the viewer IS one of the two sides, the existing single-counterparty
  presentation is kept — a p2p sender does not need to be told they were the
  sender
- Sender / receiver are derived from the ledger's principal legs, not from
  `transaction_type` — the same rule the counterparty fallback already follows
- Consistent with B13.3's per-party perspective rule: a supervisor seeing their
  downline's transaction must not thereby see figures that belong to the
  customer, only the parties and their own earning
- Frontend test: a row carrying sender and receiver renders both; a row with a
  plain counterparty renders as it does today
- Backend test: a super-agent's parent-commission row names the acting agent as
  sender and the funded customer as receiver

**Related:** B13.1 / B13.2 / B13.3 are the same statement surface. B14.1 should
be sequenced first — a wallet column and a sender/receiver pair on a row whose
amount is wrong just presents the wrong number more clearly.
