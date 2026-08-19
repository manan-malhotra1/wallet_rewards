# Base & Derived Services — Phase 2 (Mobile Client) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mobile client group transactions by *flow* rather than by exact `transaction_type`, so a derived service cannot make a user's own transaction disappear from a filter.

**Architecture:** Phase 1 shipped `base_transaction_type` on every transaction and `base_service_code` on every service tile. This phase switches the three client-side places that compare `transaction_type === 'p2p'` — a comparison that assumes the code set is closed — over to the base field. Behaviour-only change: no new screens, no API calls, no new dependencies.

**Tech Stack:** Expo SDK 54 · React Native · TypeScript · TanStack Query. Plus the Next.js `mobile-simulator/` harness, which duplicates one of the same assumptions.

**Spec:** `docs/superpowers/specs/2026-08-17-service-variants-design.md` §12 and §12.2. **Phase 1 plan (done):** `docs/superpowers/plans/2026-08-18-base-derived-services-phase1.md`.

**Branch:** `feature/base-derived-services` (continues Phase 1). Commit to it; **do not push** unless the controller says so.

**Why this phase gates production.** Until it ships, creating a derived service in production is unsafe: a derived P2P transfer would still appear in the full list but **vanish from the "Sent" filter** — the user's own money movement becomes unfindable. That is the one hard bug; the other two items are visible-but-cosmetic.

---

## Critical context for the implementer

**There is NO test harness in `mobile/`.** No `test` script, no vitest/jest, zero `*.test.ts*` files. The only automated gate is `npm run typecheck` (`tsc --noEmit`). Do **not** add a test framework as part of this plan — that is a separate decision recorded as optional Task 5. The real gate here is typecheck plus a scripted verification against the running stack.

**`mobile-simulator/` is a separate app with its own copy of the assumption.** It is a Next.js dev harness (`:3002`), not a consumer of `mobile/`'s code — it has its own `lib/backend.ts` `WalletTransaction` type and its own `transactionTypeLabel()` in `lib/format.ts`. The spec's §12 audit missed it. It needs the same treatment (Task 4), or the harness will misrepresent derived transactions during any demo.

**Repo rules that apply:** JSDoc on every function; comments explain WHY; no new dependencies; never stage `mobile/next-env.d.ts`-style generated files or `admin-ui/` work belonging to another session.

---

## File structure

| File | Responsibility |
|---|---|
| `mobile/lib/api/wallet.ts` (modify) | Add `base_transaction_type` to the `WalletTransaction` type and `base_service_code` to `MyService`; switch `activityCategory()` and `transactionTitle()` to the base field. |
| `mobile/app/transactions.tsx` (modify) | Switch the "Sent" filter to the base field — the actual bug. |
| `mobile-simulator/lib/backend.ts` (modify) | Add `base_transaction_type` to its own `WalletTransaction` type. |
| `mobile-simulator/lib/format.ts` (modify) | `transactionTypeLabel()` gains a base fallback so a derived code renders sensibly. |
| `mobile-simulator/app/_components/transaction-list.tsx` (modify) | Pass the base to the label helper. |

---

### Task 1: Types carry the base fields

**Files:**
- Modify: `mobile/lib/api/wallet.ts`

- [ ] **Step 1: Add the transaction field.** In the `WalletTransaction` interface, directly beneath `transaction_type: string;`:

```ts
  /**
   * The BASE flow this transaction belongs to. Equals `transaction_type`
   * unless it was made on a derived service (e.g. `transaction_type:
   * "p2p_diaspora"`, `base_transaction_type: "p2p"`).
   *
   * ALWAYS compare against this — never against `transaction_type` — when
   * deciding behaviour (filters, icons, direction labels). `transaction_type`
   * is an open set: an operator can add a derived service at any time, and
   * code that equality-checks it silently stops matching.
   */
  base_transaction_type: string;
```

- [ ] **Step 2: Add the service field.** In the `MyService` interface, beneath `code: string;`:

```ts
  /**
   * The base service this tile derives from, or null when it IS a base
   * service. Lets the app choose an icon/behaviour by base without knowing
   * every derived code an operator might create.
   */
  base_service_code: string | null;
```

- [ ] **Step 3: Typecheck — expect it to FAIL, and read the failures.**

Run: `cd mobile && npm run typecheck`
Expected: errors wherever a `WalletTransaction` literal is constructed without the new required field (fixtures, mocks, any local test data). **List every file `tsc` names before changing anything** — that list is the true blast radius, and it is more reliable than grepping.

- [ ] **Step 4: Fix the constructors it named.** For each: add `base_transaction_type` equal to that literal's own `transaction_type`. Do not widen the type to optional to silence this — the field is always present on the wire, and making it optional would let a `undefined` comparison silently fail closed.

- [ ] **Step 5: Typecheck — expect PASS.**

Run: `cd mobile && npm run typecheck`
Expected: clean, no output.

- [ ] **Step 6: Commit.**

```bash
git add mobile/lib/api/wallet.ts
# plus any fixture files tsc named in Step 3
git commit -m "feat(mobile): carry base_transaction_type and base_service_code

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Fix the "Sent" filter — the actual bug

**Files:**
- Modify: `mobile/app/transactions.tsx` (the `matchesFilter` function, ~line 37)

- [ ] **Step 1: Change the comparison.** Replace:

```ts
  if (filter === 'sent') return t.direction === 'out' && t.transaction_type === 'p2p';
```

with:

```ts
  // Compare the BASE flow, not the exact code: a derived P2P (e.g.
  // "p2p_diaspora") is still a P2P send, and equality-checking
  // `transaction_type` would drop it from this filter entirely — the user's
  // own transfer would be in the full list but unfindable under "Sent".
  if (filter === 'sent') return t.direction === 'out' && t.base_transaction_type === 'p2p';
```

- [ ] **Step 2: Check the sibling branches while you are here.** Read the whole `matchesFilter` body. `received` keys off `direction` only (correct, no change). The `bills` branch is a `return false` placeholder whose comment mentions a future `transaction_type === 'bill_payment'` check — update that comment to say `base_transaction_type`, so the next person implementing it does not reintroduce this bug.

- [ ] **Step 3: Typecheck.**

Run: `cd mobile && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add mobile/app/transactions.tsx
git commit -m "fix(mobile): Sent filter matches the base flow, not the exact code

A derived P2P (e.g. p2p_diaspora) appeared in the full transaction list but
vanished from the Sent filter, making a user's own transfer unfindable.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Category tint and title

**Files:**
- Modify: `mobile/lib/api/wallet.ts` (`activityCategory` ~line 118, `transactionTitle` ~line 90)

- [ ] **Step 1: `activityCategory` — switch every comparison to the base.** The function currently tests `t.transaction_type` against `'reward_issuance'`, `'redemption'`, `'top_up'` and `'p2p'`, falling through to `'generic'`. Replace each `t.transaction_type ===` with `t.base_transaction_type ===`, and add above the first comparison:

```ts
  // Base flow, not exact code — a derived P2P must keep its sent/received
  // tint rather than falling through to the generic colour.
```

- [ ] **Step 2: `transactionTitle` — same switch, plus a better fallback.** Replace each `t.transaction_type ===` with `t.base_transaction_type ===`. The final fallback currently reads:

```ts
  return t.transaction_type.replace(/_/g, ' ');
```

Leave that line **using `transaction_type`** — deliberately. Rationale to put in a comment there:

```ts
  // Fall back to the EXACT code, not the base: if an operator created a
  // derived service we cannot label, showing "cashout atm" is more honest
  // than showing "cashout" and hiding which product the user actually used.
```

- [ ] **Step 3: Typecheck.**

Run: `cd mobile && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add mobile/lib/api/wallet.ts
git commit -m "fix(mobile): category tint and title key off the base flow

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: The simulator harness (spec §12 missed this)

**Files:**
- Modify: `mobile-simulator/lib/backend.ts` (its own `WalletTransaction`, ~line 98)
- Modify: `mobile-simulator/lib/format.ts` (`transactionTypeLabel`)
- Modify: `mobile-simulator/app/_components/transaction-list.tsx` (~line 64)

`mobile-simulator/` is an independent Next.js app with its own copy of the type and its own label helper — it does not import from `mobile/`. Without this task the demo harness mislabels derived transactions.

- [ ] **Step 1: Add the field to its type.** In `mobile-simulator/lib/backend.ts`, beneath `transaction_type: string;`:

```ts
  /** The BASE flow — equals `transaction_type` unless made on a derived service. */
  base_transaction_type: string;
```

- [ ] **Step 2: Give the label helper a base fallback.** Read `transactionTypeLabel` in `mobile-simulator/lib/format.ts`. It maps known codes to labels. Add an optional second parameter and use it when the exact code is unknown:

```ts
/**
 * Human label for a transaction type. `base` is the transaction's
 * `base_transaction_type`: when the exact code is unmapped (an operator-created
 * derived service), fall back to the base's label rather than showing a raw
 * snake_case code.
 */
export function transactionTypeLabel(code: string, base?: string): string {
```

Inside, keep the existing exact-code lookup first; if it misses and `base` is provided and differs from `code`, look the base up instead; if that also misses, keep the existing final fallback. Do not change any existing mapped label.

- [ ] **Step 3: Pass the base at the call site.** In `transaction-list.tsx` line ~64:

```tsx
{transactionTypeLabel(txn.transaction_type, txn.base_transaction_type)}
```

- [ ] **Step 4: Typecheck both apps.**

Run: `cd mobile-simulator && npx tsc --noEmit`
Expected: clean, plus errors in this app's own fixtures if any construct `WalletTransaction` — fix them the same way as Task 1 Step 4.

- [ ] **Step 5: Commit.**

```bash
git add mobile-simulator/lib/backend.ts mobile-simulator/lib/format.ts mobile-simulator/app/_components/transaction-list.tsx
git commit -m "fix(mobile-simulator): label derived transactions via their base flow

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5 (OPTIONAL — controller decision, do NOT start unprompted): minimal test harness

`mobile/` has no tests at all, so the three behavioural helpers changed above
(`matchesFilter`, `activityCategory`, `transactionTitle`) are verified only by
typecheck and manual inspection. They are pure functions and would be cheap to
cover — but adding vitest to `mobile/` is a new dependency and a new gate for
the repo, which is the controller's call, not this plan's.

If approved, the shape is: add `vitest` as a devDependency, a `test` script, and
one `mobile/lib/api/wallet.test.ts` asserting that a derived `p2p_diaspora`
transaction (a) matches the Sent filter, (b) gets the `sent` category, and
(c) titles from its base. `matchesFilter` would need exporting from
`transactions.tsx` (or moving into `lib/`) to be testable.

---

### Task 6: End-to-end verification against a real derived service

This is the gate that actually proves Phase 2, because there is no test suite.
It requires the backend from Phase 1 (already on this branch) and the running
dev stack.

- [ ] **Step 1: Bring the stack up.**

Run: `scripts/dev.sh status` — if backend/admin-ui/sim are not `up`, `scripts/dev.sh start`.

- [ ] **Step 2: Create a derived service directly in the dev DB.** There is no admin UI for it yet (that is Phase 3), and the API requires platform-admin auth, so insert it with the same shape the API would produce. From the repo root:

```bash
docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform -c "
INSERT INTO services (tenant_id, code, display_name, kind, base_service_code, status)
SELECT id, 'p2p_diaspora', 'Diaspora Transfer', 'derived', 'p2p', 'active'
FROM tenants WHERE name = 'Sasai-ZA';"
```

- [ ] **Step 3: Give it pricing and limits, or it fails closed.** A derived service
without both configs is rejected with 422 before any ledger write (invariant #12).
Copy the tenant's existing `p2p` rows, changing only the type:

```bash
docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform -c "
INSERT INTO pricing_configs (tenant_id, transaction_type, account_type, currency, fixed_fee, variable_fee_pct, fee_inclusive)
SELECT tenant_id, 'p2p_diaspora', account_type, currency, fixed_fee, variable_fee_pct, fee_inclusive
FROM pricing_configs WHERE transaction_type = 'p2p';
INSERT INTO limit_configs (tenant_id, transaction_type, account_type, currency, min_amount, max_amount)
SELECT tenant_id, 'p2p_diaspora', account_type, currency, min_amount, max_amount
FROM limit_configs WHERE transaction_type = 'p2p';"
```

If either INSERT reports 0 rows, the tenant has no `p2p` config to copy — stop
and report rather than inventing fee values.

- [ ] **Step 4: Make a derived transfer.** Use the load-test script's authenticated
path, or the simulator at `http://localhost:3002`, sending a P2P with
`service_code: "p2p_diaspora"` in the request body. Confirm via psql:

```bash
docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform -c "
SELECT transaction_type, base_transaction_type, status FROM transactions
WHERE transaction_type = 'p2p_diaspora' ORDER BY created_at DESC LIMIT 3;"
```
Expected: `p2p_diaspora | p2p | COMPLETED`.

- [ ] **Step 5: Verify the client behaviour that Phase 2 exists to fix.** In the
simulator (or the Expo app if you have it running), as the sending user:
  - the transfer appears in the full transaction list ✓ (worked before this phase too)
  - **the transfer appears under the "Sent" filter** ✓ ← the bug this phase fixes
  - it carries the sent (outbound) tint, not the generic one
  - its label reads sensibly, not a raw snake_case code
  - the "Diaspora Transfer" tile appears on the home screen (already worked — `/me/services` is data-driven)

- [ ] **Step 6: Clean up the dev DB** so the branch does not leave a derived
service behind that Phase 3 would then find pre-existing:

```bash
docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform -c "
DELETE FROM pricing_configs WHERE transaction_type = 'p2p_diaspora';
DELETE FROM limit_configs WHERE transaction_type = 'p2p_diaspora';
UPDATE services SET deleted_at = now() WHERE code = 'p2p_diaspora';"
```
Leave the transactions — the ledger is append-only, and they are valid history
that now demonstrates the feature.

- [ ] **Step 7: Update the backlog.** Mark Story B4.1 Done in `docs/BACKLOG.md`
with the date and commit, and remove the "do NOT create a derived service in
production" warning's dependency on B4.1 (Phase 3 remains outstanding).

- [ ] **Step 8: Commit.**

```bash
git add docs/BACKLOG.md
git commit -m "docs(backlog): phase 2 mobile client done

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review notes (already applied)

- **Spec coverage:** §12.2 item 1 (filter) → Task 2; item 2 (`activityCategory`) → Task 3; item 3 (`transactionTitle`) → Task 3; item 4 (partner API) is **not** in this phase — it is backlog Story B4.4, since it involves third-party release cycles. §12.1's two fields → Task 1.
- **Beyond the spec:** `mobile-simulator/` (Task 4) was missed by the spec's §12 audit; it duplicates the type and the label helper independently of `mobile/`.
- **Honest gap:** no automated tests for the three changed helpers, because `mobile/` has no harness. Task 6 substitutes a scripted end-to-end proof against a real derived service; Task 5 offers the harness as an explicit opt-in.
- **Deliberate asymmetry:** behaviour switches to `base_transaction_type`, but `transactionTitle`'s *final fallback* keeps the exact code — showing "cashout atm" is more honest than hiding which product the user used.
