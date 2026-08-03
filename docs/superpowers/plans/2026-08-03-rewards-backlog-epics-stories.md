# Mode-Aware Rewards + Mobile Visibility — Backlog (Epics & Stories)

Linear-ready. Prefix `WAL-`. Maps 1:1 to the implementation plan
`2026-08-03-mode-aware-rewards-and-mobile-visibility.md` (Task N references).

---

## Epic A — Make deployment mode load-bearing

**Goal:** `tenants.business_type` (`wallet | rewards | both`) gates all reward behavior in code.
**Why:** Today the field is stored but enforces nothing; the whole feature branches on it.

### Story A1 — Business-type constants + single resolver *(Plan Task 1)*
- **As** the platform, **I** resolve a tenant's mode from one place **so that** every reward path gates consistently.
- **AC:** `business_type_of`, `rewards_from_wallet_enabled` (== `both`), `external_events_allowed` (== `rewards`) in `app/shared/tenant_mode.py`; constants on the tenants model; unit test.

### Story A2 — External Kafka events restricted to `rewards` tenants *(Plan Task 9)*
- **As** a `both`/`wallet` tenant, external events **must not** issue rewards **so that** internal wallet activity is the only reward source in `both`.
- **AC:** `process_external_event` rejects + audit-logs (`reason=wrong_mode`) any event whose tenant `business_type != rewards`; accepted for `rewards`; tests for accept + reject.

---

## Epic B — Internal wallet → rewards pipeline (`both` mode)

**Goal:** A completed rewardable wallet transaction durably drives rule evaluation and reward issuance, reconcilable, reversal-ready.
**Why:** Closes the "evaluator-not-wired-to-transactions" gap; satisfies "guard if a reward was missed".

### Story B1 — `reward_outbox` table + `reward_events.seen_at` + migration *(Plan Task 2)*
- **AC:** `RewardOutbox` model (status/attempts/last_error/transaction_id/…), `(tenant_id,status)` index, `RewardEvent.seen_at`; Alembic migration; `check_migrations` clean; tenant-isolation test.

### Story B2 — `RewardTrigger` on `PostTransactionRequest` *(Plan Task 3)*
- **AC:** Optional `reward_trigger` (user_id, transaction_type, amount, currency, merchant_id) defaulting `None`; presence is what opts a txn into rewards.

### Story B3 — `post_transaction` writes the outbox row atomically *(Plan Task 4)*
- **AC:** In `both` mode, when `reward_trigger` set and type ∈ `REWARDABLE_TYPES`, an outbox row is written in the same commit as the ledger; no row in `wallet` mode; no row without a trigger (loop avoidance). Tests for all three.

### Story B4 — Shared `evaluate_and_issue_firings` core *(Plan Task 5)*
- **AC:** Extracted from `process_external_event`; both the Kafka path and the outbox drainer call it; existing event tests still pass.

### Story B5 — Outbox drainer + immediate post-commit attempt *(Plan Task 6)*
- **AC:** `attempt_immediate(session_factory, tenant_id, user_id)` drains that user's pending rows in a fresh session, issues rewards, marks processed, returns firings; idempotent (immediate re-run issues nothing more); fail-open (records error, never raises to the money path).

### Story B6 — Celery recon sweep *(Plan Task 7)*
- **AC:** `recon_sweep_async` drains pending/retryable-failed rows across tenants; `@shared_task` wrapper on a 60s beat; test drains a forced-pending row to `processed`.

### Story B7 — Money paths trigger rewards + inline `earned_points` *(Plan Task 8)*
- **AC:** p2p (then cash_in/cash_out/airtime) set `reward_trigger` with the initiator and call `attempt_immediate` post-commit; response returns inline `earned_points`; one e2e test per service in `both` mode.

### Story B8 — Reversal claw-back hook (designed, not built) *(Plan Task 12)*
- **AC:** `reward_outbox.transaction_id` present; module docstring documents the future claw-back; a `@pytest.mark.skip` test records intent.

---

## Epic C — Mobile rewards visibility & celebration

**Goal:** Users see available rewards + progress, and get a one-shot celebration when a reward is earned.
**Why:** The requested mobile experience ("what rewards are available", "2/3 P2P", celebration graphic).

### Story C1 — `GET /me/rewards` (catalog + progress + recent) *(Plan Task 10)*
- **AC:** `enabled:false` for `wallet`; otherwise catalog of active rules for the user's segment with `{current,target,label}` progress + `status`; recent earned with `seen` flag; happy/auth(401)/tenant-isolation tests; progress projection tested for milestone & streak.

### Story C2 — `POST /me/rewards/seen` (one-shot) *(Plan Task 11)*
- **AC:** Sets `seen_at` on the caller's own reward_events; tenant/user-scoped; idempotent; test flips the flag.

### Story C3 — Mobile rewards API client *(Plan Task 13)*
- **AC:** `getRewards()` + `markRewardsSeen()` in `mobile/lib/api/rewards.ts`; typed; typecheck clean.

### Story C4 — Mobile rewards screen + home tile *(Plan Task 14)*
- **AC:** `/rewards` screen (empty state when disabled; catalog cards w/ progress bars; recent list); home "Rewards" tile routes to `/rewards`; typecheck clean.

### Story C5 — Reward celebration graphic *(Plan Task 15)*
- **AC:** `RewardCelebration` overlay fires on unseen rewards on home, then calls `markRewardsSeen` + invalidates the query; gated on `enabled`; typecheck clean.

---

## Suggested delivery order

A1 → B1 → B2 → B3 → B4 → B5 → B6 → B7 → A2 → C1 → C2 → C3 → C4 → C5 → B8.
(Backend foundation first; A2 after the pipeline so mode-gating lands as a set; mobile last; reversal-hook test to close.)

## Rollout flag

No new flag — gated by existing `business_type`. **Note:** existing `both` tenants
begin issuing wallet-driven rewards the moment Epic B lands. Confirm this is the
intended go-live before deploying B7.
