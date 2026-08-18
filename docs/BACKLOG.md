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
