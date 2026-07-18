---
paths:
  - "backend/app/modules/ledger/**"
  - "backend/app/modules/payments/**"
  - "backend/app/modules/redemption/**"
  - "backend/app/modules/rewards/**"
---

# Ledger invariants

These rules govern every code path that writes to `ledger_entries`. They are non-negotiable.

## 1. Append-only

- The application MUST NOT issue `UPDATE` or `DELETE` against `ledger_entries`.
- Reversal = a new entry with opposite direction (the original DEBIT spawns a CREDIT reversal, and vice versa).
- The original entry's `status` field is the only thing that may change (PENDING → COMPLETED/REVERSED), and even that is via the parent `transactions.status`, not the ledger row.

## 2. Double-entry

Every transaction produces at least one DEBIT and one CREDIT. The amounts balance. System-wide:

```
SUM(amount WHERE entry_type='CREDIT' AND status='COMPLETED')
- SUM(amount WHERE entry_type='DEBIT' AND status='COMPLETED')
= 0
```

This is invariant NFR-0100. There is a test in `tests/invariants/test_ledger_sum_to_zero.py` that runs against the test DB after every test session. It must always pass.

## 3. Status transitions

```
PENDING → COMPLETED
PENDING → FAILED
PENDING → REVERSED
```

A `COMPLETED` or `FAILED` transaction is terminal. No further transitions. (REVERSED is also terminal, but reachable from PENDING during reconciliation.)

## 4. Idempotency

Every transaction request carries an `Idempotency-Key`. The unique constraint `(tenant_id, idempotency_key)` on `transactions` is the structural guard. If a duplicate arrives, the service returns the existing transaction's response without writing new ledger entries.

## 5. Fund reservation before external calls

For any payment that requires an external call:

1. Inside the DB transaction: insert PENDING `ledger_entries` (the reservation).
2. Commit. Close the DB transaction.
3. Make the external call.
4. On success: update `transactions.status='COMPLETED'`; the PENDING ledger entries become effective.
5. On failure: insert REVERSAL `ledger_entries`; update `transactions.status='REVERSED'`.
6. On timeout: leave PENDING. Reconciliation job (Module 12) resolves it.

External calls MUST NOT happen inside an open DB transaction (NFR-0130, Pay-PRD-0270).

## 6. Overdraft prevention

A transaction that would make `available_balance` (= `balance` − `reserved`) go negative MUST be rejected BEFORE any ledger entry is created. The authoritative check lives in `post_transaction`'s balance guard (invariant #11), which locks the guarded account `FOR UPDATE` and re-checks under that lock (endpoint-level checks are advisory early rejections).

**Float floor.** The same overdraft floor now also applies to the **operator cash float** (`system_cash_inflow`): it is a POSITIVE balance that must be pre-funded from the bank (CREDIT float / DEBIT `operator_adjustment` bank mirror, e.g. via `treasury.adjust_system_wallet`) before it can fund users. A net DEBIT of the float that would drive it below zero is rejected with a distinct `InsufficientFloat` (409, `insufficient_float`) — `InsufficientFunds` stays reserved for a user `financial_wallet` overdraft. Every float-sourced funding is affected: admin `fund` / `fund_user`, external partner fund, and any reward (e.g. referral cashback) that debits the float. A fund REVERSAL credits the float back, so it is a net credit and never floored. The float has no `max_balance` ceiling. Other system / pool accounts (bank mirrors, merchant collection, points) remain unfloored.

## 7. Reward double-issuance prevention

Reward issuance is structurally protected by:

```sql
CREATE UNIQUE INDEX idx_reward_events_idempotency
    ON reward_events (user_id, rule_id, triggering_event_id);
```

The application MUST rely on this index — never use a "check-then-insert" pattern. Catch the integrity error and treat it as "already issued, no-op". (NFR-0110.)

## 8. What goes in the ledger

Only money and points movements. Configuration changes, audit events, notifications — these go to their own tables. The ledger is purely the source of truth for account balances.

## 9. Currency

Every ledger entry carries `currency CHAR(3)`. Cross-currency operations are out of scope for Phase 1 (PRD §5 non-goal). The platform never auto-converts.

## 10. Reversal naming convention

When writing a reversal entry, the new entry's `transaction_id` should be the SAME as the original (so they group), but a new `id`. The reversal entry has the opposite `entry_type` and the same `amount`. Comments in the code must make clear which row is the original and which is the reversal.
