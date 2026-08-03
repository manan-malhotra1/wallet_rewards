# Mode-Aware Internal Rewards + Mobile Rewards Visibility — Design

**Date:** 2026-08-03
**Status:** Approved (brainstorming) → planning
**Owner:** Manan

## Problem

Today the rewards engine is reachable **only** through the external Kafka path
(`process_external_event` — Kafka consumer / admin HTTP / dev sim). A completed
wallet transaction never drives rule evaluation: `post_transaction`
(`backend/app/modules/ledger/service.py:127`) emits no events and never calls
`evaluate_active_rules_for_event`. This is the known "evaluator-not-wired-to-
transactions" gap.

Separately, `tenants.business_type` (`'wallet' | 'rewards' | 'both'`,
`backend/app/shared/models/tenants.py:48`) exists and is admin-editable but
**gates no behavior anywhere in code**.

We want, for a `both`-mode tenant, wallet transactions to feed the rewards
engine directly; the mobile app to show available rewards and the user's
progress toward them; and a reward-earned signal so the app can play a
celebration graphic — all correctly gated by deployment mode.

## Goals

1. In `both` mode, a completed **rewardable** wallet transaction evaluates rules
   and issues rewards — durably (no reward silently lost) and reconcilably.
2. Make `business_type` load-bearing: `wallet`, `rewards`, `both` each behave
   per the matrix below, enforced in code.
3. Mobile: `GET /me/rewards` returns available reward rules + per-user progress
   (e.g. "2 / 3 P2P transfers") and recently-earned rewards with an unseen flag.
4. A reward-earned signal drives a mobile celebration graphic; the app marks it
   seen so it fires once.

## Non-Goals (this cut)

- Reversal claw-back **logic** (design the hook only; reversals don't exist yet).
- Push notifications (inline response + unseen flag instead).
- Redemption catalog changes; referral-on-transaction wiring (separate gap).

## Deployment-mode behavior matrix

| Mode | Internal wallet → rewards | External Kafka events | `GET /me/rewards` |
|---|---|---|---|
| `wallet` | ❌ no outbox, no evaluator | ❌ rejected in code (and consumer not run) | `{enabled: false}` — mobile hides rewards UI |
| `rewards` | ❌ (no wallet) | ✅ **only** mode where external events issue rewards | ✅ |
| `both` | ✅ outbox + evaluator + issuance | ❌ external events rejected for `both` tenants | ✅ |

## Architecture

### 1. Internal wiring (`both` mode): transactional outbox + immediate + recon

```
money service (p2p/cash_in/cash_out/airtime)
   │  builds PostTransactionRequest with reward_trigger = {user_id, txn_type, amount, currency, merchant_id}
   ▼
post_transaction(session, request)             # ledger/service.py — the one choke point
   ├─ balance guard (invariant 11)
   ├─ INSERT reward_outbox row  ── IF request.reward_trigger set AND business_type == 'both'
   └─ COMMIT                     ── ledger entries + outbox row land atomically
   │
   ▼  (back in the money service, AFTER commit — invariant 6)
rewards.outbox.attempt_immediate(tenant_id, user_id)   # new session
   ├─ SELECT pending rows for (tenant,user) FOR UPDATE SKIP LOCKED
   ├─ evaluate_and_issue_firings(session, event)        # shared with process_external_event
   ├─ mark row processed
   └─ return list[FiringOut]  → money service returns earned rewards inline

Celery beat: rewards.outbox.recon_sweep()      # drains any pending/failed rows left behind
```

- **Durability / "guard if a reward was missed":** the outbox row is written in
  the **same DB transaction** as the ledger commit, so the *intent* to evaluate
  can never be lost. The recon sweep draining stuck rows **is** the
  reconciliation ("missed rewards" == "stuck outbox rows").
- **Idempotency:** issuance uses `triggering_event_id = str(transaction_id)`, so
  the existing `reward_events` unique index (`idx_reward_events_idempotency` on
  `(user_id, rule_id, triggering_event_id)`) makes the immediate attempt and the
  recon sweep safe to both run — no double-issue.
- **Loop avoidance:** only money services set `reward_trigger`. Reward issuance
  itself (`issue_points_reward` / `issue_cashback_reward` → `post_transaction`
  with no `reward_trigger`) writes no outbox row, so rewards never reward rewards.
  Defense-in-depth: `reward_trigger.transaction_type` must be in
  `REWARDABLE_TYPES` (`p2p`, `cash_in`, `cash_out`, `airtime`).

### 2. Mode gating — enforcement points

- **`post_transaction`**: writes the outbox row only when `business_type == 'both'`.
- **`process_external_event`**: after the existing tenant-scope check, **reject +
  audit-log** any event whose tenant `business_type != 'rewards'`
  (`outcome="rejected"`, reason `wrong_mode`). External Kafka thus feeds rewards
  **only** for rewards-only tenants — enforced in code, independent of which
  process happens to run the consumer.
- **`GET /me/rewards`**: returns `{enabled: false, ...}` for `wallet` tenants.

A single resolver, `app/shared/tenant_mode.py::business_type_of(session, tenant_id)`,
is the one reader; constants live on the tenants model.

### 3. Mobile API

**`GET /me/rewards`** → `RewardsOut`:
```json
{
  "enabled": true,
  "catalog": [
    { "rule_id": "…", "name": "Send 3 to friends", "description": "…",
      "reward_type": "points", "reward_value": "200", "currency": null,
      "status": "in_progress",
      "progress": { "current": 2, "target": 3, "label": "P2P transfers" } }
  ],
  "recent": [
    { "reward_event_id": "…", "rule_name": "First transfer", "reward_type": "points",
      "value": "50", "currency": null, "earned_at": "2026-08-03T…", "seen": false }
  ]
}
```
- `catalog`: active rules admitting the user's segment, each projected to
  `{current, target, label}` from `user_rule_progress` + the rule's target;
  `status ∈ locked | in_progress | earned`.
- `recent`: latest `reward_events` (desc, capped) with a `seen` flag.

**`POST /me/rewards/seen`** `{ "reward_event_ids": ["…"] }` → sets
`reward_events.seen_at = now()` for the caller's own rows; idempotent.

**Celebration:** `recent[]` where `seen == false` drives the graphic; the app
calls `POST /me/rewards/seen` after showing it. The p2p/txn responses continue to
return inline `earned_points` for the instant hit.

### 4. Reversal-ready hook (designed, not built)

`reward_outbox.transaction_id` records the source transaction. When reversals are
implemented, the reversal transaction will emit its own outbox row; a handler
will look up the original `reward_events`, post an append-only claw-back (DEBIT
the user's points back to `system_points_issuance`) and decrement
`user_rule_progress`. No claw-back logic is built now — the column + module
docstring capture the hook, and a skipped test records the intent.

## Data model changes

- **New `reward_outbox`** (`backend/app/shared/models/rewards.py`):
  `id` (UUID pk), `tenant_id` (UUID, indexed), `user_id` (UUID),
  `transaction_id` (UUID, FK `transactions.id`), `transaction_type` (str),
  `amount` (Numeric), `currency` (str), `merchant_id` (UUID | null),
  `status` (str: `pending`/`processed`/`failed`, default `pending`),
  `attempts` (int, default 0), `last_error` (str | null),
  `created_at`, `processed_at` (nullable). Index on `(tenant_id, status)`.
- **`reward_events.seen_at`** (`TIMESTAMP NULL`) — drives unseen celebrations.
- Alembic migration for both; tenant-isolation test for `reward_outbox`.

## Error handling

- Immediate attempt failures are swallowed (money movement already succeeded —
  rewards fail-open) but recorded on the row (`status='failed'`, `attempts++`,
  `last_error`); the recon sweep retries up to `MAX_ATTEMPTS`.
- `process_external_event` rejection path reuses the existing `_log_rejected`
  audit machinery.

## Testing

- **Mode matrix**: `both` issues internally; `rewards` issues only via Kafka path;
  `wallet` issues nothing and `/me/rewards` is disabled.
- **Outbox**: row written atomically with ledger; immediate attempt issues;
  recon drains a forced-`pending` row; idempotent (immediate + recon → one reward).
- **Loop avoidance**: a `reward_issuance` transaction writes no outbox row.
- **`process_external_event`**: accepts `rewards` tenant, rejects `both`/`wallet`
  (audit-logged).
- **`GET /me/rewards`**: happy / auth (401) / tenant-isolation; progress projection
  for milestone & streak. **`POST /me/rewards/seen`**: flips `seen_at`, tenant-scoped.
- Mobile: frontend automation deferred (per coding guidelines) — typecheck only.

## Rollout

Ships behind the existing `business_type` field; no new flag. Existing `both`
tenants begin issuing rewards from wallet activity as soon as the outbox path
lands. External-only (`rewards`) tenants are unaffected except for the new
same-mode rejection guard.
