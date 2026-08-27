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


## The three guard shapes (amended 2026-08-26 — commission wallets)

`post_transaction` enforces two INDEPENDENT axes at the choke point. They used
to coincide, and one of them used to be inferred. Neither is true any more.

| Account type | Floor (≥ 0) | Ceiling (`max_balance`) | Rolling caps |
|---|---|---|---|
| `financial_wallet` | yes (`InsufficientFunds`) | yes | yes |
| `system_cash_inflow` | yes (`InsufficientFloat`) | no | no |
| `cashback_provider_wallet` | yes (`InsufficientCashbackFunds`) | no | no |
| `commission_wallet` | yes (`InsufficientCommissionBalance`) | **no** | **no** |

**Why this needed an explicit set.** The ceiling branch previously read
`account.user_id is not None`. That was correct only while `financial_wallet`
was the sole *user-owned* guarded type — every other guarded account was a
system account with a NULL `user_id`, so "has an owner" and "has a ceiling"
happened to mean the same thing.

`commission_wallet` breaks that coincidence: it is user-owned AND uncapped, by
design (an agent may accrue any amount of commission). Had it simply been added
to `_OVERDRAFT_GUARDED_ACCOUNT_TYPES`, the ownership test would have silently
applied `max_balance` to commission accrual — a bug no commission test would
catch, because it only fires once an agent's accrual crosses their configured
cap in production.

So the ceiling is now its own explicit membership set:

```python
_CEILING_GUARDED_ACCOUNT_TYPES = frozenset({ACCOUNT_TYPE_FINANCIAL_WALLET})
```

**Rule for any new account type:** decide its membership in BOTH
`_OVERDRAFT_GUARDED_ACCOUNT_TYPES` and `_CEILING_GUARDED_ACCOUNT_TYPES`
deliberately, and give it a DISTINCT floor exception so an operator can tell
which account needs replenishing. Never let a type inherit a guard by accident
of having (or not having) a `user_id`.

### Which rows are locked (amended 2026-08-27 — B15)

The guarded SET says which account types *have* a guard. It is not the same as
which rows get **locked** on a given transaction. A row is locked only when a
check will actually fire on it:

| Leg | Locked? |
|---|---|
| net DEBIT on a floor-guarded type | yes — the floor runs |
| net CREDIT on `financial_wallet` | yes — `max_balance` runs |
| net CREDIT on `financial_wallet`, but `is_reversal` or `skip_receive_cap` | **no** — the ceiling is skipped |
| net CREDIT on any other guarded type | **no** — uncapped, nothing to check |
| any leg on an unguarded type | no |

Before this, any non-zero delta on a guarded type was locked. That meant a
credit into an uncapped wallet took a `FOR UPDATE` held through commit and was
then checked against nothing — and because parent commission credits the same
super-agent's commission wallet on every downline cash-in, an entire downline
serialised on one row.

**Why dropping those locks is safe.** A credit only ever INCREASES a balance, so
a concurrent debit that reads without seeing an uncommitted credit sees LESS
than the truth and errs toward rejecting. Conservative, never permissive — a
floor cannot be breached by a lock that was not taken on a credit. Two credits
racing on a CAPPED wallet still both lock, which is what preserves the M-01
`max_balance` race.

Locks are still acquired in canonical account-id order. Narrowing the set cannot
introduce a deadlock cycle that a larger set did not already have.

**Rule:** if you add a guard, decide which SIDE it fires on and make
`_needs_lock` say so. Locking a leg no check will read is contention with no
safety value, and the row you are locking may belong to someone with a large
downline.
