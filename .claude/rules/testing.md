---
paths:
  - "backend/tests/**"
  - "admin-ui/**/*.test.ts"
  - "admin-ui/**/*.test.tsx"
  - "admin-ui/**/*.spec.ts"
  - "admin-ui/**/*.spec.tsx"
---

# Testing conventions

## Backend (pytest)

- `pytest` + `pytest-asyncio` + `httpx.AsyncClient`.
- Tests run against real PostgreSQL (test DB), not SQLite. Schema parity matters.
- Fixtures live in `backend/tests/conftest.py`: `async_client`, `db_session`, `test_tenant`, `test_user`.
- Each test runs in a transaction that rolls back at teardown — no test pollution.

### Naming

Tests describe the rule, not the function:

```python
# Good
def test_milestone_rule_resets_counter_after_trigger():
    ...

# Bad
def test_rule_service_1():
    ...
```

### Required coverage per endpoint

- Happy path
- At least one auth failure (401/403)
- At least one validation failure (422)
- Tenant isolation: request as Tenant A user trying to read Tenant B data → 404 or 403
- Idempotency: identical request with same Idempotency-Key returns same response, no duplicate DB row

### Invariant tests

`backend/tests/invariants/` runs at the end of every test session:

- `test_ledger_sum_to_zero` — `SUM(CREDIT) - SUM(DEBIT) = 0` across all accounts
- `test_no_orphan_ledger_entries` — every entry has a parent `transaction`
- `test_no_completed_transaction_without_entries` — every `COMPLETED` transaction has ≥ 2 entries

These exist to catch architectural drift, not to fail individual feature tests.

### Rules engine tests

For each of the 7 rule types, at minimum:
- `test_<type>_fires_when_threshold_met`
- `test_<type>_does_not_fire_when_below_threshold`
- `test_<type>_idempotent_re_evaluation`
- Type-specific tests: streak break, composite AND vs OR, campaign date range, etc.

## Frontend (admin-ui)

Frontend automation testing is ACTIVE (previously deferred — see
`coding-guidelines.md` §4).

- Vitest + Testing Library for unit/integration, on a jsdom environment.
- Harness: `admin-ui/vitest.config.ts` + `admin-ui/vitest.setup.ts`. The setup
  file registers jest-dom matchers, an `afterEach(cleanup)`, and the jsdom
  polyfills Radix UI needs (`scrollIntoView`, pointer-capture, `matchMedia`).
- The `@/` alias is read from `tsconfig.json` so it tracks the build.
- Playwright for E2E happy paths (Phase 2; not required for MVP).

### What to test

- `lib/` helpers: pure functions (labels, scope keys, formatters, diffing).
- Form components: valid submit, invalid validation, server-error display.
- Tables: sort, filter, multi-select, bulk action.
- Command palette: open via ⌘K, fuzzy search, command execution.
- Use Testing Library queries (`getByRole` / `getByLabelText`), not
  implementation details. Mock server actions via `vi.mock` on the route's
  `_actions` module — never call the backend from a component test.

### Running

```bash
cd admin-ui
npm test          # vitest run — non-interactive, exits (use in CI)
npm run test:watch # watch mode for local development
```

## What to mock

- **External APIs** (Mukuru, MTN, Keycloak admin) — mock with httpx Respx or similar.
- **Kafka** — use a test producer that captures emitted messages for assertion.

## What NOT to mock

- **PostgreSQL** — always use the real test DB. Mocking the ORM hides real schema bugs.
- **Time** — use `freezegun` for time-sensitive tests; don't shim datetime.
- **The application's own service functions** — test through the endpoint, not the internal function. (Mocking your own code couples tests to implementation.)

## Coverage threshold

80% line coverage on `backend/app/` and `admin-ui/lib/`. Routes and pages aren't part of the coverage gate; they get tested through endpoint/integration tests.

## Running

```bash
# Backend
cd backend && make test

# Admin UI
cd admin-ui && npm test
```
