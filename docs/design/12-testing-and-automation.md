# 12 — Testing & Quality Automation

> **Document type:** Design (HOW). How the platform is tested — the backend pytest harness (API + Kafka +
> ledger invariants), the admin-ui Vitest harness, the enforcement gates, and the leadership test report.
> **Related:** [`.claude/rules/testing.md`](../../.claude/rules/testing.md) (the source rule — this doc explains
> how it is *wired*, it does not restate it), [`.claude/rules/coding-guidelines.md`](../../.claude/rules/coding-guidelines.md)
> §3 (backend tests) + §4 (frontend Vitest), [`.claude/rules/python-backend.md`](../../.claude/rules/python-backend.md)
> (per-endpoint test rule).
> **README:** see the [design index](README.md) §8. Enforces the invariants in [README §5](README.md) (money core).
> **Audience:** an engineer adding an endpoint, a consumer, a money service, or an admin-ui component.

---

## 1. Philosophy

Two rules drive everything here:

1. **Every backend interface another system can call has automated tests** — every FastAPI endpoint, every Kafka
   producer/consumer, every model with state transitions (coding-guidelines §3). Tests run against **real
   PostgreSQL**, never SQLite — schema parity is a feature, not an accident (mocking the ORM hides real schema
   bugs).
2. **Money paths are guilty until proven balanced.** The append-only ledger and the `post_transaction` choke
   point ([02-ledger](02-ledger-accounts-and-money-movement.md)) are backed by structural invariant tests and
   fail-closed tests that a new money service *must* ship before it merges.

Frontend automation is **active** (previously deferred): Vitest + Testing Library on jsdom, carrying `lib/`
helpers and the high-value interactive components behind money/config maker-checker flows.

What we deliberately **don't** chase: 100% coverage, tests that mock our own service functions (test through the
endpoint), or shimming time/DB (`freezegun` for time, real DB always).

---

## 2. The backend harness (`backend/tests/`)

**Stack:** `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"` in `backend/pyproject.toml`) +
`httpx.AsyncClient` driving the ASGI app in-process. 154 test modules across ~40 domain packages
(`backend/tests/<domain>/`), each mirroring a `backend/app/modules/<domain>` folder.

Config lives in `backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 2.1 The shared test DB and its contention caveat

Everything hangs off [`backend/tests/conftest.py`](../../backend/tests/conftest.py):

| Concern | How it works | Why |
|---|---|---|
| Test DB | `wallet_platform_test` (the app DB name with `_test` appended) | schema parity with prod; never SQLite |
| Engine | one async engine, `poolclass=NullPool` | asyncpg allows one op per connection; a pooled connection shared across pytest-asyncio coroutines throws `another operation in progress` |
| Schema | `create_all` **once per session** (`_prepare_schema`, autouse, `drop_all` at teardown) | fast; the migration chain is checked separately by `check_migrations.py` |
| Isolation | `TRUNCATE … RESTART IDENTITY CASCADE` of every table **at the start** of each `db_session` (not rollback) | SAVEPOINT rollback can't be shared between a fixture session and the endpoint's own session on one asyncpg connection |
| App wiring | `async_client` overrides `get_async_session` with a fresh `TestSessionLocal()` per request | fixture-committed rows are visible to the endpoint and vice versa |

> **Contention caveat — run ONE suite at a time.** Concurrent pytest runs (e.g. two agent sessions) share the
> single `wallet_platform_test` database. The session-scoped `drop_all/create_all` and per-test `TRUNCATE` of one
> run wipe the other's rows mid-flight; they deadlock or fail spuriously. Run one backend suite at a time; if a
> run is wedged, `pkill` **only your own** stuck process. (See MEMORY: *shared test-DB contention*.)

### 2.2 Core fixtures

- `db_session` — per-test `AsyncSession`; TRUNCATEs before yielding, commits freely.
- `session_factory` — the `async_sessionmaker` itself, for code (the reward-outbox drainer) that opens its own
  sessions per unit of work.
- `async_client` — `httpx.AsyncClient` on the ASGI app with the session override installed.
- `test_tenant` / `other_tenant` — a `both`-mode ZAR/USD tenant pair; **the ZAR cash float is pre-funded** via
  `prefund_float()` so money tests don't trip the no-overdraft float floor (invariant #11). Float-floor tests
  must use a *fresh, un-prefunded* tenant.
- `test_user` + `default_user_role` (grants `p2p`, `redemption`, `fund`, `airtime_recharge`), `user_wallet`,
  `user_points`, `system_points_account`.
- **Auth fixtures without a real Keycloak:** an in-process RSA-2048 keypair per session seeds the JWKS cache
  (`seed_keycloak_jwks`, autouse) and blocks any real JWKS fetch; `make_admin_token` mints signed
  Keycloak-shaped JWTs (override to test expired / wrong-issuer / unknown-kid / missing-role). User sessions are
  fabricated directly in Redis via `create_session_token_for_user` — no OTP+PIN dance per test.
- **Per-test Redis** (`_redis_per_test`, autouse) — a fresh redis-py async client is created **and monkeypatched
  into every module that imported the singleton** (`sessions`, `lockout`, `rate_limit`), then `flushdb`'d.
  pytest-asyncio gives each test a new event loop, so a reused client would hit `Event loop is closed`.

### 2.3 Required coverage per endpoint

Every endpoint ships this matrix (coding-guidelines §3, python-backend.md, testing.md):

| Case | Assertion |
|---|---|
| Happy path | 2xx, correct body, side effect occurred |
| Auth failure | missing/invalid token → **401** |
| Permission failure | valid token, wrong role/permission → **403** |
| Validation failure | bad body → **422** |
| Tenant isolation | Tenant A acting on Tenant B's resource → **404/403** (a failing isolation test is a PR blocker) |
| Idempotency | identical request + same `Idempotency-Key` → same response, **no duplicate row** |

Test names describe the **rule**, not the function (`test_milestone_rule_resets_counter_after_trigger`, not
`test_rule_service_1`).

### 2.4 Money / ledger invariant tests

[`backend/tests/invariants/`](../../backend/tests/invariants/) is the structural safety net — belt-and-braces
checks that catch architectural drift even though `post_transaction` already rejects bad writes:

- `test_ledger_sum_to_zero_holds_after_writes` — across all `COMPLETED` entries, `SUM(CREDIT) − SUM(DEBIT) = 0`.
- `test_ledger_entries_have_no_updated_at_column` — queries `information_schema.columns`; an `updated_at` on
  `ledger_entries` would break the append-only guarantee, so its appearance fails the build intentionally.

Money-service test packages (`ledger/`, `payments/`, `cashin/`, `cashout/`, `airtime/`, `redemption/`,
`external/`) additionally assert:

| Property | Where |
|---|---|
| Append-only (reversal appends opposite legs; no UPDATE) | `ledger/test_post_transaction.py` |
| Double-entry preserved / reversal nets to zero | `ledger/` + per-service |
| Idempotent creation (same key → one transaction) | every money endpoint |
| Balance guard: overdraft reject, `max_balance` ceiling, reversal cap-exemption, account classification | `ledger/test_balance_guard.py` |
| Cash-float no-overdraft floor → `InsufficientFloat` 409 | `ledger/test_float_floor.py` |
| Earned-commission credit is cap-exempt | `ledger/test_commission_cap_exempt.py` |
| Receive/send-cap **concurrency** proofs | live with the endpoints (p2p receive cap, external fund/withdraw races) |

### 2.5 Fail-closed pricing + limits — mandatory for every new money service

Invariant #12 (README §5): a money service may run only if **both** a pricing config **and** a limit config
resolve for the acting user's type — else `422` **before any ledger write**, unconditionally.
[`backend/tests/pricing/test_service_gating.py`](../../backend/tests/pricing/test_service_gating.py) drives
`require_pricing_and_limits` directly and asserts `ServiceNotConfigured` when pricing-only, limit-only, or
neither is seeded. Additional `*fail_closed*` tests exist for step-up (`step_up/test_enforce_fail_closed.py`)
and the money paths.

> **Rule for a new money `transaction_type`:** it MUST ship tests asserting it 422s when the pricing config is
> missing **and** when the limit config is missing. The `code-review` agent blocks any new/edited money path
> that skips this.

### 2.6 Kafka producer / consumer tests

The mandate (coding-guidelines §3): producers assert **emit-after-commit**, correct **topic**, **`user_id`
partition key**, and message **schema**; consumers assert process-**once**, **dedup** via `event_ingestion_log`,
**integrity-failure → audit** (never mutates state), and **schema-mismatch → logged with reason**.

**As-built reality (be honest):** core money modules emit **no external Kafka** — wallet→rewards coupling uses a
transactional **outbox** (`reward_outbox`, written inside `post_transaction`), tested in
`rewards/test_outbox_internal.py` and the per-service reward tests (`payments/test_p2p.py`,
`cashin/`, `cashout/`). External Kafka lives only in the events/rewards area. Event **ingestion** (registered
sources, HMAC proof-of-origin, dedup, schema) is covered by `events/test_ingest_event.py`,
`events/test_source_registration.py`, `events/test_sim_routes.py` (the latter asserts `missing_user_id → 422`,
enforcing the `user_id` partition-key requirement). The full **Kafka-produce happy path is not unit-tested** —
it needs a live broker; `events/test_sim_routes.py` documents this and defers it to a future
`KAFKA_AVAILABLE=true` integration suite. When a real producer/consumer lands, the full matrix above applies.

### 2.7 What to mock (and not)

| Mock | Don't mock |
|---|---|
| External APIs (Mukuru, MTN, Keycloak admin) — httpx respx or similar | **PostgreSQL** — always the real test DB |
| Kafka — a capturing test producer for assertions | **Time** — use `freezegun`, don't shim `datetime` |
| | **Your own service functions** — test through the endpoint, not the internal call |

---

## 3. Running the backend suite & the checks

```bash
cd backend
make test     # pytest -v
make check    # ruff check + ruff format --check + mypy app/ + scripts/check_migrations.py
make seed     # python ../scripts/seed.py (seed data for manual/dev runs)
```

- **`make check`** is the pre-commit gate: `ruff` lint + format check, `mypy` in **strict** mode
  (`[tool.mypy] strict = true`), and `check_migrations.py`.
- **`scripts/check_migrations.py`** wraps `alembic check` — it fails non-zero if the SQLAlchemy models have
  drifted from the migration head. This enforces invariant #3 (*no DDL outside Alembic*): you cannot change a
  model without shipping a matching migration. Run it before every commit.
- **`/commit` skill** chains lint + type check + `alembic check` + unit tests before a commit lands.

> **Full-suite runs are user-triggered.** The shared test DB makes a full sweep slow and contention-prone;
> default to a targeted subset (`pytest tests/<domain>`) and only run the whole suite on explicit request.
> (MEMORY: *full suite run is user-triggered*.)

---

## 4. The admin-ui harness (`admin-ui/`)

**Stack:** Vitest 2 + Testing Library (`@testing-library/react` + `user-event` + `jest-dom`) on a **jsdom**
environment. 61 test files, co-located `*.test.ts` / `*.test.tsx` next to source.

### 4.1 Config — [`admin-ui/vitest.config.ts`](../../admin-ui/vitest.config.ts)

- `environment: "jsdom"`, `globals: true`, `include: ["**/*.test.{ts,tsx}"]`, `node_modules`/`.next` excluded.
- `testTimeout`/`hookTimeout` bumped to **20s** — jsdom + `user-event` + Radix dialogs flake at the 5s default
  under full-suite parallel load.
- The `@/` alias is **derived from `tsconfig.json` `paths` at load time** (`aliasRootFromTsconfig()`), so the
  test alias can never drift from what Next.js and `tsc` resolve at build.

### 4.2 Setup — [`admin-ui/vitest.setup.ts`](../../admin-ui/vitest.setup.ts)

Loaded before every file: registers `jest-dom` matchers; `afterEach` runs Testing Library `cleanup()` **and**
`vi.useRealTimers()` (a test that opts into fake timers must not leave them for the next file — that hangs
`user-event`); polyfills the DOM APIs jsdom omits that Radix primitives call (`scrollIntoView`,
`hasPointerCapture`/`setPointerCapture`/`releasePointerCapture`, `matchMedia`) — without these, opening a Radix
Dialog/Select throws.

### 4.3 What is tested & the golden rule

| Target | Examples |
|---|---|
| `lib/` pure helpers (labels, scope keys, formatters, diffing) — **fast, DOM-free, carry the coverage gate** | `lib/money-operation-label.test.ts`, `lib/config-scope.test.ts`, `lib/approvals-filter.test.ts`, `lib/brand-palette.test.ts` |
| Interactive components behind **money/config maker-checker** flows | the `system-wallets/` dialogs (fund/withdraw/adjust/bank-mirror), `pricing/`, `limits/`, `commissions/`, `step-up/`, `config-requests/`, `money-operations/`, `user-operations/` drawers |
| Command palette (⌘K, fuzzy search, command execution) | `components/command-palette/command-palette.test.tsx` |

> **Golden rule — never hit the backend.** Client components call `"use server"` actions in the route's
> `_actions.ts`; component tests `vi.mock` that `_actions` module and assert the mocked action is called with the
> right args and its result is surfaced. Example
> ([`reconciliation/_components/sweep-button.test.tsx`](../../admin-ui/app/(authenticated)/reconciliation/_components/sweep-button.test.tsx)):
> `vi.mock("@/app/(authenticated)/reconciliation/_actions", …)`, click the real button, `waitFor` the action
> call + the toast. Use Testing Library **role/label queries** (`getByRole`, `getByLabelText`), never
> implementation details.

### 4.4 Running

```bash
cd admin-ui
npm test          # vitest run — non-interactive, exits (CI)
npm run test:watch
```

### 4.5 Deferred (honest status)

- **Playwright E2E is partially built, not fully deferred.** The rules docs call E2E "Phase 2 / not required for
  MVP", but the repo already carries `admin-ui/playwright.config.ts`, `@playwright/test`, ~9 specs under
  `admin-ui/e2e/` (step-up, access-lock, treasury-adjust, config-approval, approvals, fund-user, user-ops,
  dashboard, identifier), and `npm run e2e` scripts. Treat E2E as **opt-in / not gated** — it is not part of
  `npm test` or any commit gate yet.
- **Mobile (Expo) automation tests** — none. Deferred.

---

## 5. Coverage gate

testing.md and coding-guidelines set **80% line coverage on `backend/app/` and `admin-ui/lib/`** (routes and
pages are excluded — they are covered through endpoint/component tests).

> **Reality note:** the 80% figure is a **standard, not a wired gate.** `pytest-cov` is present
> (`backend/requirements-dev.txt`) but neither `make test`/`make check` nor `npm test` pass a `--cov`/coverage
> flag, and there is no `[tool.coverage]` block or Vitest `coverage` config enforcing a threshold. Coverage is
> measured on demand, not failed-on in CI. See §7.

---

## 6. Ownership & enforcement

| Owner | Scope | Triggers |
|---|---|---|
| **`automation-testing`** agent | **all backend tests** — API, Kafka producer/consumer, ledger invariants, tenant isolation | after every new endpoint, consumer, producer, or model with state transitions; when `code-review` flags missing coverage |
| **`admin-ui`** agent | frontend (Vitest) tests — `lib/` helpers + interactive components | alongside the admin-ui component/helper it ships |
| **`code-review`** agent | **blocks** merges with missing coverage or a money path skipping the fail-closed tests | before every feature commit; on any change touching ledger/payments/redemption/auth/external |
| Path-scoped rules | auto-loaded by file path (`testing.md`, `python-backend.md`, `ledger-invariants.md`, `kafka.md`) | on edit |
| `/commit` skill | lint + type + `alembic check` + tests | before a commit lands |

(Per CLAUDE.md — frontend tests are owned by the `admin-ui` agent, **not** `automation-testing`.)

---

## 7. Business-readable test descriptions & the leadership report

**Convention (MEMORY: *test descriptions = "Verify <user outcome>"*).** On **both** stacks, every test-case
description starts with **"Verify "** followed by a plain user-facing guarantee — not a mechanism, tuple, or
locator. A test describable only by an internal detail is a smell.

- **Backend:** the pytest function's **docstring first line** —
  `"""Verify every completed transaction balances to zero across accounts"""`.
- **Frontend:** the `it(...)` title — `it("Verify an admin can run a reconciliation sweep", …)`.

These feed the **combined leadership HTML report**. It is real and wired:

```bash
make report          # repo root: runs BOTH suites (recording on) + renders test-reports/index.html
make report-html     # re-render from existing run files — fast, runs no tests
```

- **Backend recorder** — `backend/tests/conftest.py` hooks `pytest_runtest_logreport` / `pytest_sessionfinish`;
  gated by `SASAI_TEST_REPORT=1`, it writes per-test outcome + duration to `test-reports/backend-run.json` (a
  normal `make test` writes nothing). Exposed as `make test-report` in the backend Makefile.
- **Frontend recorder** — `npm run test:report` runs Vitest with the JSON reporter →
  `test-reports/frontend-run.json`.
- **Renderer** — [`scripts/build_test_report.py`](../../scripts/build_test_report.py) joins the raw outcomes
  with each test's description (Python: docstring via **AST**; frontend: the `it` title), its section (test
  dir / top `describe`) and subsection (file), a rolling PASS/FAIL history of the last 3 builds, and a
  git-derived "last updated" date (per-function `git log -L` for backend, per-file for frontend). Output:
  `test-reports/index.html` — one page, Backend / Frontend tabs. Pure reporting; never touches app code or the
  DB.

The "Verify …" convention is what makes that page legible to leadership: every row reads as a guaranteed user
outcome, so the report doubles as a plain-English catalogue of what the platform promises.

---

## 8. Stale-vs-real notes (as of 2026-08-05)

Where the source rule and the as-built config disagree — flagged so a reader trusts the code, not the doc:

1. **Coverage is a standard, not a gate.** testing.md says "80% line coverage" as if enforced; nothing in
   `make test`/`make check`/`npm test` actually runs coverage or fails a build on it (§5).
2. **Playwright/E2E is "Phase 2 / deferred" in the rules but already exists** — `playwright.config.ts`, ~9
   `admin-ui/e2e/*.spec.ts`, and `npm run e2e` scripts are in the repo (§4.5). It is simply not gated.
3. **Named invariant tests that don't exist as written.** testing.md lists `test_no_orphan_ledger_entries` and
   `test_no_completed_transaction_without_entries` as running each session; the only file in
   `backend/tests/invariants/` is `test_ledger_sum_to_zero.py` (sum-to-zero + no-`updated_at`). Those two extra
   invariants are asserted implicitly by the per-service ledger tests, not as standalone session-end checks.
4. **"Kafka producer/consumer tests" describe a future state.** No external Kafka producer/consumer exists in
   the money core; the wallet→rewards path is a DB outbox, and the one true producer (event sim route) has its
   happy path explicitly deferred to a broker-gated suite (§2.6).
```
