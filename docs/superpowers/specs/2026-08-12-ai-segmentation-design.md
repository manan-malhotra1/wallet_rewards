# AI-Powered Segmentation — Design

**Date:** 2026-08-12
**Status:** Approved (brainstorm 2026-08-12)
**Builds on:** Segments module (Epic 10 / WAL-79 — static cohorts, `segments` + `user_segments`)

## 1. Summary

Evolve segments from static admin-assigned cohorts into a criteria-driven segmentation
engine, organised into **segment groups**, with seeded default tiers (Gold/Silver/Bronze
etc.) and an **AI segment builder**: an admin describes a cohort in natural language and a
tenant-configured LLM compiles it into the platform's criteria DSL for review and creation.

Delivered in two phases, each independently shippable:

- **Phase 1 — Foundation (no AI):** segment groups, criteria DSL + batch evaluator,
  seeded default groups/segments, manual criteria builder in the admin UI.
- **Phase 2 — AI layer:** per-tenant AI provider config (encrypted key), natural-language →
  DSL draft endpoint, preview-then-create UI flow.

### Decisions locked during brainstorm

| Question | Decision |
|---|---|
| Membership exclusivity | **Exclusive within a group** (one tier per lens), multiple groups per user. Overlap inside a group resolved by segment `priority` (highest wins). |
| Evaluation timing | **Scheduled batch** (Celery beat, hourly default) + manual "Recompute now". Real-time/event-driven deferred. |
| AI key configuration | **Per-tenant AI config**: provider + model + API key, encrypted at rest, masked in UI, never logged. No key → AI builder hidden; manual builder always available. |
| Criteria vocabulary | **Curated metric set (~10 metrics)**, AND/OR one level deep, thresholds. Additive over time. |

## 2. Data model (Phase 1)

All tables carry `tenant_id` (invariant #7). DDL via Alembic only (invariant #3).

### `segment_groups` (new)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK tenants | indexed |
| `name` | VARCHAR(100) | unique per tenant |
| `description` | VARCHAR(500) NULL | |
| `is_system` | BOOL default false | seeded groups; rename/delete protected |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Membership within a group is always **exclusive** in v1 (no `membership` mode column —
YAGNI; add later if overlapping groups are needed).

### `segments` (altered)

| New column | Type | Notes |
|---|---|---|
| `group_id` | UUID FK segment_groups, **NOT NULL** | Migration seeds a per-tenant "General" system group and backfills existing segments into it. |
| `criteria` | JSONB NULL | NULL = static/manual segment (today's behaviour, unchanged). Non-null = dynamic. |
| `priority` | INT NOT NULL default 0 | Higher wins inside an exclusive group (Gold=3 > Silver=2 > Bronze=1). |
| `is_system` | BOOL default false | Seeded defaults: criteria/priority editable, name/delete protected. |
| `last_evaluated_at` | TIMESTAMPTZ NULL | Stamped by the evaluator. |

### `user_segments` (altered)

| New column | Type | Notes |
|---|---|---|
| `source` | VARCHAR(10) NOT NULL default 'manual' | `'manual'` \| `'criteria'`. Recompute only inserts/deletes rows with `source='criteria'`; hand-assigned members are never touched. |

Rules and multipliers keep reading `user_segments` unchanged — zero downstream change.

### `tenant_ai_configs` (Phase 2, new)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK tenants, unique | one config per tenant |
| `provider` | VARCHAR(20) | `'anthropic'` (v1; enum CHECK) |
| `model` | VARCHAR(100) | default `claude-opus-5` |
| `api_key_encrypted` | TEXT | Fernet-encrypted; master key from backend env (`AI_CONFIG_MASTER_KEY`). |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

API responses expose only `api_key_last4`. The key is a credential under NFR-0170: never
logged, never in audit `before/after_state` (store `"***"+last4`), never returned in full.

## 3. Criteria DSL

One versioned JSON schema — the single contract shared by the manual builder, the seed
data, the evaluator, and the AI compiler. Validated by a Pydantic model
(`SegmentCriteria`) in `backend/app/modules/segments/criteria.py`.

```json
{
  "v": 1,
  "op": "AND",
  "conditions": [
    { "metric": "txn_sum", "txn_type": "p2p", "window_days": 90, "gte": 5000 },
    { "metric": "days_since_last_txn", "lte": 14 }
  ]
}
```

- `op`: `AND` | `OR`; 1–10 conditions; **one level** (no nesting) in v1.
- Comparators per condition: at least one of `gte` / `lte` / `eq` (numeric).
- `txn_type` (optional) and `window_days` (optional, 1–365) apply only to transactional
  metrics; the validator rejects them elsewhere.

### Metric vocabulary (v1)

| Metric | Filters | Source |
|---|---|---|
| `txn_count` | `txn_type?`, `window_days?` | COMPLETED transactions |
| `txn_sum` | `txn_type?`, `window_days?` | COMPLETED transactions, amount sum |
| `wallet_balance` | — | SUM(ledger_entries) financial wallet |
| `points_balance` | — | points account balance |
| `points_redeemed` | `window_days?` | redemptions |
| `rewards_earned` | `window_days?` | reward_events count |
| `account_age_days` | — | users.created_at |
| `days_since_last_txn` | — | latest COMPLETED transaction |
| `referral_count` | — | converted referrals |

New metrics are additive: register a name + an aggregate SQL builder in one metric
registry module; the schema enum and the AI prompt derive from the registry (single
source of truth, no drift).

## 4. Evaluator (Phase 1)

`backend/app/modules/segments/evaluator.py`, invoked two ways:

- **Celery beat**: per-tenant task, hourly by default (interval env-configurable).
- **Manual**: `POST /api/v1/segments/recompute?tenant_id=...` (platform-admin) — enqueues
  the same task; also `POST /api/v1/segments/{id}/preview` for a dry-run matched-count.

Algorithm per tenant:

1. Collect dynamic segments (`criteria IS NOT NULL`), grouped by `group_id`.
2. Compute each referenced metric **once per user** with set-based SQLAlchemy aggregates
   (ORM only, invariant #4; no per-user loops).
3. Evaluate criteria per user per segment; within each group keep only the
   highest-`priority` matching segment (ties broken by created_at, oldest wins —
   deterministic).
4. Diff against current `user_segments WHERE source='criteria'`; bulk insert/delete the
   delta. Manual rows untouched.
5. Stamp `last_evaluated_at`; write one audit_log entry per changed segment
   (`action='segment.recomputed'`, actor `'system'` or the admin id, after_state =
   `{added: N, removed: M, member_count}`) — membership churn itself is not per-user
   audit-logged (volume).

No ledger writes, no Kafka emission in v1. Evaluation is read-only over
transactions/ledger plus writes to `user_segments`.

## 5. Defaults (seed)

`make seed` creates three system groups with tiered segments (criteria editable in UI):

| Group | Segments (priority) | Default criteria sketch |
|---|---|---|
| Customer Loyalty | Gold (3) / Silver (2) / Bronze (1) | txn_count 90d ≥ 20 / ≥ 5 / ≥ 1 |
| Transaction Value | High (3) / Mid (2) / Low (1) | txn_sum 90d ≥ 10000 / ≥ 1000 / > 0 |
| Engagement | Active (3) / New (2) / Dormant (1) | days_since_last_txn ≤ 14 / account_age ≤ 30 / days_since_last_txn > 60 |

Plus the "General" system group that hosts legacy/static segments.

## 6. AI layer (Phase 2)

### Tenant AI config

- Module `backend/app/modules/ai_config/` (router/service/schemas):
  `GET/PUT /api/v1/ai-config` (platform-admin, tenant-scoped), key write-only.
- Admin UI: settings card under Tenants — provider, model, key input (masked), "Test
  connection" button (sends a trivial prompt, reports ok/fail).

### Draft endpoint

`POST /api/v1/segments/ai-draft` (platform-admin) — body: `tenant_id`, `prompt` (free
text, ≤ 1000 chars), optional `group_id` for context.

Flow (service `backend/app/modules/segments/ai_builder.py`):

1. Load tenant AI config; 404 `ai_config_missing` if none.
2. Call the provider **outside any DB transaction** (invariant #6), timeout-wrapped
   (30s), using the official `anthropic` **AsyncAnthropic** SDK.
3. Request uses **structured outputs**: `output_config={"format": {"type": "json_schema",
   "schema": <criteria JSON schema>}}` so the response is guaranteed schema-valid JSON.
   System prompt = DSL contract + metric registry vocabulary + tenant's active
   `txn_type` codes + group names. The model gets **no tools and no data access** — it is
   a pure NL→DSL compiler.
4. Re-validate the output with the same `SegmentCriteria` Pydantic model (defence in
   depth). On validation failure: one retry appending the validation error; then 422
   `ai_draft_invalid`.
5. Return `{criteria, suggested_name, suggested_group_id?, explanation}` — a **draft
   only**; nothing is persisted by this endpoint.
6. Audit log `segment.ai_draft` with prompt text + model + validity outcome (prompt is
   admin-authored config text, not PII; the API key never appears).

Guardrails: per-tenant rate limit (10 drafts/min via the existing rate-limit helper);
provider errors map to 502 `ai_provider_error` with the provider's message sanitised;
refusals (`stop_reason == "refusal"`) map to 422 `ai_draft_refused`.

### UI flow

"New segment" dialog gains a first step when AI is configured: describe the segment in
plain English → draft returned → criteria rendered **in the manual builder** (fully
editable) with live preview count → admin picks group/name/priority → create. Without an
AI config the dialog opens directly in the manual builder.

## 7. API surface summary

| Endpoint | Phase | Notes |
|---|---|---|
| CRUD `/api/v1/segment-groups` | 1 | platform-admin; delete blocked while segments exist |
| `POST/PATCH /api/v1/segments` | 1 | gains `group_id`, `criteria`, `priority`; validation via `SegmentCriteria` |
| `POST /api/v1/segments/{id}/preview` | 1 | dry-run matched-user count for given criteria |
| `POST /api/v1/segments/recompute` | 1 | enqueue tenant recompute |
| `GET/PUT /api/v1/ai-config` | 2 | key write-only, last4 readable |
| `POST /api/v1/segments/ai-draft` | 2 | NL → criteria draft |

State-mutating endpoints carry Idempotency-Key per invariant #2 (draft endpoint is
read-only in effect — no persistence — and exempt; recompute is idempotent by nature but
still accepts the header).

## 8. Admin UI (Phase 1 unless noted)

- Segments page → group-sectioned: accordion per group; segments as priority-ordered rows
  with member count, window/criteria summary, `last_evaluated_at`, static/dynamic badge.
- Group CRUD dialogs; "Recompute now" button with progress toast.
- Manual criteria builder component: metric select (from a `/segments/metrics` vocabulary
  endpoint), comparator + threshold inputs, AND/OR toggle, add/remove condition rows,
  live preview count (calls `/preview`).
- Phase 2: AI describe-first step in the create dialog; AI settings card.

## 9. Testing

Backend (pytest, real Postgres):
- Criteria validator: accept/reject cases per metric, filter misuse, nesting rejection.
- Evaluator: per-metric correctness; exclusivity + priority resolution; deterministic
  ties; manual rows preserved; idempotent recompute (second run = no diff); tenant
  isolation (tenant A recompute never touches tenant B rows).
- Endpoints: happy/401/403/422/tenant-isolation/idempotency per testing.md for every new
  endpoint.
- AI draft (respx-mocked provider): valid draft; invalid JSON → retry → 422; timeout →
  502; refusal → 422; missing config → 404; key never in logs (caplog assertion).

Frontend (Vitest): criteria-builder component (add/remove/validate conditions), group
accordion rendering, AI-step gating on config presence; lib helpers (criteria summary
formatter) unit-tested.

## 10. Out of scope (v1)

- Real-time / event-driven membership updates (batch only).
- Nested criteria expressions, percentile ranks ("top 5%").
- Overlapping-membership groups (all groups exclusive).
- Segment entry/exit side effects (notifications, auto-rewards).
- Non-Anthropic providers (schema allows adding an enum value later).
- Membership history table (only current membership + audit summaries).
