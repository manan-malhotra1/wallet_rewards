# Admin UI — Playwright E2E harness

End-to-end browser tests that drive the **real** admin UI against a **live**
backend + Keycloak. Distinct from the Vitest unit/component suite:

| Harness | Owns | Run with |
|---|---|---|
| Vitest | `**/*.test.{ts,tsx}` (lib helpers, components) | `npm test` |
| Playwright | `e2e/**/*.spec.ts` (full-stack flows) | `npm run e2e` |

The two never collect each other's files (`testMatch: /.*\.spec\.ts/` here,
`include: **/*.test.{ts,tsx}` in Vitest).

## What's covered

19 tests across 14 specs (2 auth setup + 17 scenarios). Every maker-checker
flow opens a second browser context as a *different* admin, because a maker
approving their own proposal is exactly what the pipeline must refuse.

| Spec | Flow |
|---|---|
| `dashboard.spec.ts` | Authenticated `/` redirects to `/dashboard`; app shell + nav render. |
| `approvals.spec.ts` | `/approvals` shows the role-gated tabs (Configuration / Transactions / Users) + status filter. |
| `config-approval.spec.ts` | **Maker-checker**: ZAR tax-rate edit → Propose → checker approves → the new rate shows on `/taxes`. |
| `step-up.spec.ts` | **Maker-checker**: step-up threshold change proposed, then approved by a different admin. |
| `treasury-adjust.spec.ts` | **Maker-checker**: cash-float top-up proposed and approved; the float balance rises. |
| `fund-user.spec.ts` | **Maker-checker**: fund Alice; her ZAR wallet available balance rises by the exact amount. |
| `user-ops.spec.ts` | **Maker-checker**: edit Alice's name through the Users queue. |
| `user-types.spec.ts` | **Maker-checker**: propose a Retail user type under `super_agent`, approve, and it appears Active. Also pins the two-level depth cap (D7) — the parent dropdown never offers a child type. |
| `access-lock.spec.ts` | Lock Alice's login (confirm dialog) → "Login locked" pill, then Restore access. |
| `identifier.spec.ts` | Add an account-number identifier to Alice, then verify it. |
| `commission-disbursement.spec.ts` | Mixed batch upload + approval; self-approval refused; rejection is terminal. |
| `commission-withdrawal.spec.ts` | Clawback requires a destination and applies once approved; batch menus stay separated. |
| `commission-wallet-balance.spec.ts` | An agent's commission wallet is listed separately from their main wallet. |

### Gotcha: the user-detail sections are collapsed tabs

`/users/<id>` renders Personal & KYC, Address & country, KYC documents,
Accounts & balances and Transactions as a single row of tabs that all start
**closed** (`section-tabs.tsx`, `defaultOpenId = null`). Nothing inside a
closed tab is in the DOM. Any spec touching a user's wallets or identifiers
must click its tab first — `getByRole("tab", { name: "Accounts & balances" })`.
Two specs broke silently when that layout landed; this is why.

### Known gaps

No coverage yet for pricing, limits, campaigns/rules, segments, redemption
rates, services, API keys, merchants or instruments.

## Auth model (important)

The admin UI does **not** redirect to Keycloak's hosted login page — it renders
its own credentials form at `/login`, and the Keycloak password grant runs
server-side inside next-auth's `authorize()` callback.

`e2e/auth.setup.ts` is a Playwright **setup project** that every spec depends
on. It signs in **two** dev admins once and saves each session:

| Admin (email) | Role in tests | storageState |
|---|---|---|
| `admin-test@example.test` | maker | `e2e/.auth/admin-test.json` |
| `admin-approver@example.test` | checker | `e2e/.auth/admin-approver.json` |

Two sessions are required because maker-checker forbids self-approval: the admin
who proposes a change cannot approve it. Both admins hold
`platform-admin` + `config/treasury/user-approver` (see
`scripts/bootstrap_keycloak.py`). Specs load the right storageState via
`test.use({ storageState })`; `step-up.spec.ts` opens the checker in a second
browser context.

Password comes from `E2E_ADMIN_PASSWORD`, defaulting to the dev constant
`admin-test-pass`. No real secret is hardcoded. `e2e/.auth/` is git-ignored
(it holds live Keycloak tokens).

## Run recipe (green run — needs the full stack up)

From the repo root:

```bash
# 1. Infra — Postgres, Kafka, Keycloak, Redis (all in Docker)
cd sasai-wallet-infra && docker compose up -d
bash kafka/topics.sh                     # after Kafka is healthy

# 2. Backend schema, Keycloak realm + dev admins, seed data
cd ../backend
source .venv/bin/activate                 # (create + pip install -r requirements.txt first time)
alembic upgrade head
python ../scripts/bootstrap_keycloak.py   # seeds admin-test + admin-approver
make seed                                 # seeds Alice (+27825550001), Bob, tenant, step-up policy

# 3. Start backend (leave running)
make dev                                  # uvicorn on :8000

# 4. Start admin UI (leave running, separate terminal)
cd ../admin-ui
npm run dev                               # :3000

# 5. Run the E2E suite (separate terminal)
cd admin-ui
npm run e2e
```

`playwright.config.ts` has a `webServer` with `reuseExistingServer: true`
pointing at `npm run dev` / http://localhost:3000, so step 5 **attaches** to the
dev server from step 4 rather than fighting it. (If none is running it will try
to start one, but the backend + Keycloak from steps 1–3 must be up regardless.)

Backend at `http://localhost:8000`, Keycloak at `http://localhost:8080`, admin
UI at `http://localhost:3000`. Override the UI origin with `E2E_BASE_URL` if
needed.

## First install

```bash
cd admin-ui
npm install                    # @playwright/test is already a devDependency
npx playwright install chromium
```

## Failure artefacts + report

On failure Playwright auto-captures a **screenshot**, **video**, and **trace**
under `test-results/`. Open the HTML report (with the trace viewer) via:

```bash
npx playwright show-report      # or: npm run e2e:report
```

Other entry points:

```bash
npm run e2e:ui                  # interactive UI mode (pick/step through tests)
npx playwright test step-up     # run a single spec
npx playwright test --list      # enumerate specs without running (static check)
```

## Note on selectors

Specs use resilient role/label/text queries. The interactive flows
(`step-up.spec.ts`, `access-lock.spec.ts`) are a best-guess from the current
components and depend on seed data (a step-up policy; user Alice). Expect to fine
-tune a selector or two on the first live run — that's normal for a fresh
harness.
