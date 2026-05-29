---
paths:
  - "**/*"
---

# Coding Master Guidelines — READ FIRST, ALWAYS

These guidelines OVERRIDE any default coding behaviour. They are the user's explicit
preferences for this project and apply to every file in the repo.

---

## 1. Simple code, no duplicates, easy to maintain

### Simplicity
- One function = one thing. If you can't describe it in one sentence, split it.
- Function bodies stay under ~40 lines. Files stay under ~400 lines. Hard limits are not
  the point — the limit is "a new reader can hold the whole thing in their head".
- No premature abstraction. Three repeated lines beat a wrong abstraction.
- No half-finished implementations, no "TODO" stubs that pretend to be working code.
- No feature flags or backwards-compatibility shims unless explicitly required.

### Duplication
- **Before writing a new function, grep for an existing one.** Search before you write.
- DRY threshold: 2 occurrences = consider a util; 3 = must be a util.
- Before adding a helper to `shared/utils/`, check if one already exists there.
- Before adding a new exception class, check `shared/exceptions/`.
- Before adding a Pydantic schema, check `shared/schemas/`.

### Maintainability
- Name things so the code reads like English. Functions = verbs, variables = nouns.
- No clever one-liners. Boring code is good code.
- Pure functions where possible. Side effects concentrated and named.
- If a function takes more than ~5 parameters, group them into a dataclass or schema.

---

## 2. Comments in files and functions — REQUIRED

> **This OVERRIDES any default "minimal comments" instruction.** The user has explicitly
> asked for documentation in this project. Always include the comments described below.

### Every file
- Top-of-file docstring: 1–3 lines describing what the module does and any
  non-obvious context (e.g. which PRD requirement it satisfies).

### Every function and class
- Docstring explaining:
  - **Purpose** (one sentence)
  - **Arguments** (if any are non-obvious)
  - **Returns** (if non-trivial)
  - **Raises** (custom exceptions only)
  - **Invariants / side effects** if any (e.g. "emits a Kafka event after commit")
- Use Google-style docstrings for Python, JSDoc for TypeScript.

### Inline comments
- Comments explain **WHY**, not WHAT.
- Required for: financial state transitions, idempotency tricks, security-sensitive
  branches, external API quirks, performance hacks.
- Not required for: well-named one-liners, obvious assignments.

### Examples

**Good Python docstring:**
```python
async def reverse_transaction(txn_id: UUID, session: AsyncSession) -> Transaction:
    """Reverse a COMPLETED transaction by appending opposite ledger entries.

    Per the ledger invariants (.claude/rules/ledger-invariants.md), we never UPDATE
    existing entries; we append new ones with opposite direction. The transaction
    row's status moves PENDING -> REVERSED.

    Args:
        txn_id: The transaction to reverse. Must currently be PENDING.
        session: Async DB session, committed by the caller.

    Returns:
        The updated Transaction with status='REVERSED'.

    Raises:
        TransactionNotFoundError: txn_id does not exist in this tenant.
        InvalidStatusTransition: transaction is not in PENDING state.

    Side effects:
        Inserts new ledger_entries rows. Does NOT emit Kafka (caller does).
    """
```

**Good TypeScript JSDoc:**
```typescript
/**
 * Render a status pill for any transaction-like entity.
 * Uses the colour token matching the status (PENDING -> warning, COMPLETED -> success, etc.).
 * The compact variant is for dense table rows; full variant for detail screens.
 */
export function StatusPill({ status, compact = false }: Props) { ... }
```

---

## 3. Backend automation tests — REQUIRED for every exposed interface

Every backend interface that another system can call MUST have automated tests:

### APIs (FastAPI endpoints)
- Happy path
- Auth failure (401)
- Permission failure (403)
- Validation failure (422)
- Tenant isolation (cross-tenant access returns 404 / 403)
- Idempotency (same Idempotency-Key returns same response, no duplicate side-effect)

### Kafka producers
- Emit-after-commit verified (DB commit before send)
- Correct topic, correct partition key (always `user_id`)
- Message schema validated

### Kafka consumers
- Happy path: event processed once, side effect occurs
- Duplicate event: event_ingestion_log dedup works, no double-processing
- Integrity failure: rejected events logged to audit, never affect state
- Schema mismatch: failed event logged with reason

### Ledger / financial code
- Append-only verified (no UPDATE issued against ledger_entries)
- Double-entry balance preserved
- Idempotency on transaction creation
- Reversal flow: original + reversal both present, balance net-zero
- The ledger_sum_to_zero invariant test runs after every test session

### Coverage
- 80% line coverage on `backend/app/`
- The `automation-testing` agent is responsible for writing and maintaining all of this.

---

## 4. Frontend automation tests — DEFERRED

Frontend (admin-ui) automation testing is intentionally deferred to a later phase.

- Do NOT write Vitest/Playwright tests for admin-ui unless explicitly asked.
- Do NOT block frontend PRs on missing tests.
- Manual smoke testing in the browser is the current bar.

When this changes, update this file and update `automation-testing` agent's scope.

---

## 5. How these guidelines are enforced

| Mechanism | When |
|---|---|
| Self-check while writing code | Every edit |
| `code-review` agent | Before any commit of feature work; on multi-file changes |
| `automation-testing` agent | After every endpoint / consumer / producer is added |
| Path-scoped rules in `.claude/rules/` | Loaded automatically based on file path |
| `/commit` skill | Lint + type check + test gate before commit lands |

If any guideline conflicts with a more specific path-scoped rule (e.g. `ledger-invariants.md`),
the more specific rule wins for that path.
