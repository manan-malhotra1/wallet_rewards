# Sasai Wallet & Rewards Platform

A multi-tenant wallet + rule-based rewards engine for Sasai Fintech's diaspora ecosystem. Three per-tenant deployment modes (`business_type`: wallet / rewards / both), append-only ledger, Kafka-backed event ingestion, Keycloak-secured admin, PIN/OTP for users, and an Expo mobile app.

**Source of truth (all in-repo):** [Product PRD](docs/02-prd.md) (the *what* — requirements + `Pay-PRD-####` IDs), [Epics & Stories](docs/09-epics-and-stories.md) (delivery tracking), and [Design docs](docs/design/README.md) (the *how* — per-module implementation). System-level summaries: [Technical Architecture](docs/05-technical-architecture.md) + [Data Architecture](docs/06-data-architecture.md). When this file conflicts with the PRD, the PRD wins on intent; the design docs win on current implementation.

> ## ⚠ READ FIRST: [Coding Master Guidelines](.claude/rules/coding-guidelines.md)
>
> Every file edit in this repo must comply with the coding master guidelines:
> simplicity, no duplication, **mandatory file + function docstrings**, and
> **automation tests for every backend interface** (APIs and Kafka). Frontend
> automation testing is deferred. The `code-review` and `automation-testing`
> agents enforce these.

## Stack (locked by Technical PRD)

| Layer | Tech | Version |
|---|---|---|
| Backend | Python · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 | 3.12 / 0.136.3 / 2.0.50 / 1.18.4 |
| Database | PostgreSQL | local instance |
| Bus | Apache Kafka · confluent-kafka | Docker |
| Auth | Keycloak (admin) · custom PIN/OTP (users) | Docker |
| Queue | Celery · Redis | latest |
| Admin UI | Next.js 16.2.6 · TypeScript · App Router · shadcn/ui · Tailwind v4 · next-auth v5 | Node 22.22.2 |
| Mobile | Expo (SDK 54) · React Native · expo-router · Tamagui · Skia · TanStack Query | Node 22.22.2 |

## Repo layout

| Path | What lives here |
|---|---|
| `backend/app/modules/{module}/` | Per-domain service (`router.py`, `service.py`, `schemas.py`) — ~27 modules |
| `backend/app/shared/models/` | SQLAlchemy ORM, one file per domain |
| `backend/app/shared/exceptions/` | All custom exceptions (one file, all subclass `AppHTTPException`) |
| `backend/app/auth/` | Keycloak JWT, Redis sessions, bcrypt hashing, HMAC callbacks, API-key + rate-limit |
| `backend/alembic/versions/` | Migrations (`YYYYMMDD_NNNN_description.py`) |
| `admin-ui/app/(authenticated)/` | Next.js admin (App Router; server components + `_actions.ts` server actions) |
| `mobile/app/` | Expo mobile app (expo-router file-based screens) |
| `sasai-wallet-infra/` | Docker Compose (Postgres, Kafka, Keycloak, Redis) + `kafka/topics.sh` |
| `scripts/` | `seed.py`, `check_migrations.py`, `bootstrap_keycloak.py`, `run_consumer.py` |
| `docs/` | Vision, PRD, epics, `design/` (per-module HOW), architecture, UX/UI, security threat models |
| `.claude/` | Agents, skills (incl. `local-setup`), rules, memory |

## Non-negotiable invariants

These come from PRD requirements. Never violate.

1. **Ledger is append-only.** Reversals = new ledger entry. Balance = `SUM(ledger_entries)` per account. No UPDATE on ledger.
2. **Every state-mutating endpoint has an idempotency key.** Duplicate keys return the original result (Pay-PRD-0200).
3. **No DDL outside Alembic.** Run `python scripts/check_migrations.py` before commit.
4. **No raw SQL.** SQLAlchemy ORM only.
5. **Routers contain no business logic.** Routers → services.
6. **External calls happen after DB commit.** Never inside a transaction (NFR-0130).
7. **`tenant_id` is in every domain table.** Never hardcode; resolve from auth token.
8. **Kafka events emit after DB commit.** Consumers are idempotent (check `event_ingestion_log`).
9. **Never log credentials.** PINs, OTPs, session tokens never appear in logs, audit records, or error messages (NFR-0170).
10. **Topics use `user_id` as partition key.** Preserves per-user event order.
11. **Balance limits are enforced under a wallet row-lock at the ledger choke point — never re-derived per endpoint.** Balance is `SUM(ledger_entries)`, so no single row self-serializes concurrent writers: a check-then-act on the derived balance races two transactions past the cap (the M-01 class of bug — see [ledger-invariants.md](.claude/rules/ledger-invariants.md)). Every money path funnels through `post_transaction`, so the guard is enforced there and nowhere else: for each **user financial wallet** leg AND the **operator cash float** (`system_cash_inflow`) leg it locks that account row `FOR UPDATE` in canonical (account-id-sorted) order, then enforces overdraft (on any net debit) under that lock, held through commit; the `max_balance` ceiling (on any net credit) applies to the user wallet only. (Rolling daily/weekly/monthly receive & send caps stay in the limits service — they are advisory, not part of this guard.) Services MUST NOT hand-roll a balance read plus a credit/debit. Corollaries: (a) the cash float `system_cash_inflow` now carries a **non-negative overdraft floor** at the choke point — it must be pre-funded from the bank (via `treasury.adjust_system_wallet`, CREDIT float / DEBIT bank mirror) before it can fund users; a net debit that would drive it below zero is rejected with a distinct `InsufficientFloat` (409). It has **no** `max_balance` ceiling (no `user_id`), so a top-up credit is never blocked. All OTHER accounts that are not `financial_wallet` — pool / merchant *collection* accounts such as `airtime_merchant_holding`, the `operator_adjustment` bank mirror, points accounts — carry neither floor nor cap and are skipped by the guard; (b) reversals / refunds are cap-**exempt** (fail-open): restoring funds may legitimately push a wallet past `max_balance` and must never be blocked — a fund reversal credits the float back and so is never floored either; (c) new transaction types inherit the guard automatically simply by going through `post_transaction` — any type that DEBITs the float is now floored.
12. **Every money-moving service fails closed on missing config — pricing AND limits, unconditionally.** A service (`transaction_type`) may execute only if BOTH a pricing config AND a limit config resolve for the acting user's type/scope; if either is absent the request MUST be rejected **before any ledger write** (422 `pricing_config_missing`, or the limits equivalent). This is **not** gated by any per-tenant flag or environment — it always applies (Pay-PRD-0420). Silent zero-fee / limitless pass-through is **forbidden**; a zero fee or an unlimited limit must be an *explicitly configured* row, never an implicit default. **No `try/except PricingConfigMissing: return 0`-style swallow** on any transaction path. Every money path must call `require_pricing_and_limits(...)` before charge assembly, and **every new service MUST ship tests asserting it 422s when the pricing config is missing and when the limit config is missing** (see `backend/tests/*/test_*fail_closed*`/boundary tests for the pattern). The `code-review` agent blocks any new/edited money path that skips this.

## Commands

```bash
# Infra — everything in Docker, no host-installed services
cd sasai-wallet-infra && docker compose up -d
bash kafka/topics.sh   # after Kafka is healthy

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
make seed
make dev          # uvicorn + reload
make check        # alembic check + ruff + mypy
make test         # pytest

# Admin UI
cd admin-ui
npm install
npm run dev       # :3000
```

## Agents

| Agent | Owns |
|---|---|
| [lead](.claude/agents/lead/SKILL.md) | Orchestrates work across agents, commits, PRs |
| [backend](.claude/agents/backend/SKILL.md) | FastAPI modules, routers, services |
| [data](.claude/agents/data/SKILL.md) | SQLAlchemy models, Alembic migrations, ledger invariants |
| [rules-engine](.claude/agents/rules-engine/SKILL.md) | Module 9 — seven rule types, progress tracking |
| [admin-ui](.claude/agents/admin-ui/SKILL.md) | Next.js admin pages and components |
| [platform](.claude/agents/platform/SKILL.md) | Keycloak auth, Kafka topics, tenant config |
| [infra](.claude/agents/infra/SKILL.md) | Docker Compose, deployment |
| [compliance](.claude/agents/compliance/SKILL.md) | PII handling, audit trail, retention, KYC/AML hooks |
| [code-review](.claude/agents/code-review/SKILL.md) | **Reviews every change before commit.** Checks coding guidelines, architecture rules, ledger invariants, security, test coverage, PRD traceability. |
| [automation-testing](.claude/agents/automation-testing/SKILL.md) | **Writes all backend tests** (API + Kafka + ledger). Frontend tests deferred. |
| [security](.claude/agents/security/SKILL.md) | **VAPT + threat modeling specialist.** Adversarial. Owns STRIDE threat models, OWASP API Top 10 testing, fintech-specific exploit scenarios, dependency CVE scanning, crypto review. |

### When the review / testing / security agents trigger automatically

- **`code-review`** runs before every commit of feature work; on any change touching >3 files; on any change touching ledger / payments / redemption / auth / external APIs; on user request.
- **`automation-testing`** runs after every new endpoint, every new Kafka consumer/producer, every new model with state transitions, every new rule type; when `code-review` flags missing coverage; on user request.
- **`security`** runs on every new module touching auth / money / PII; on every auth or session flow change; on every new external integration; on every dependency major-version bump; quarterly full sweep; post-incident; on user request.

## Rules (path-scoped)

| File | Applies to |
|---|---|
| [`coding-guidelines.md`](.claude/rules/coding-guidelines.md) | **All files** — master coding standards, always loaded |
| [`python-backend.md`](.claude/rules/python-backend.md) | `backend/**/*.py` |
| [`frontend-admin.md`](.claude/rules/frontend-admin.md) | `admin-ui/**/*.{ts,tsx}` |
| [`database.md`](.claude/rules/database.md) | `backend/app/shared/models/**`, `backend/alembic/**` |
| [`ledger-invariants.md`](.claude/rules/ledger-invariants.md) | `backend/app/modules/{ledger,payments,redemption}/**` |
| [`kafka.md`](.claude/rules/kafka.md) | `backend/app/modules/events/**` and all producers/consumers |
| [`testing.md`](.claude/rules/testing.md) | `backend/tests/**`, `admin-ui/**/*.test.{ts,tsx}` |
| [`observability.md`](.claude/rules/observability.md) | All files |
| [`compliance-fintech.md`](.claude/rules/compliance-fintech.md) | All files |

## Quick references

- Product PRD (the *what* — requirement IDs + acceptance criteria): [docs/02-prd.md](docs/02-prd.md)
- Epics & Stories (delivery tracking, Shipped/Partial/Planned): [docs/09-epics-and-stories.md](docs/09-epics-and-stories.md)
- Design docs (the *how* — start at the HLD): [docs/design/README.md](docs/design/README.md)
- Glossary: PRD section 3
- Tech architecture: [docs/05-technical-architecture.md](docs/05-technical-architecture.md)
- Data architecture: [docs/06-data-architecture.md](docs/06-data-architecture.md)
- UX philosophy / UI layouts (admin): [docs/03-ux-philosophy.md](docs/03-ux-philosophy.md) · [docs/04-ui-layouts.md](docs/04-ui-layouts.md)
- First-time local setup (infra → backend → admin → mobile): [.claude/skills/local-setup/SKILL.md](.claude/skills/local-setup/SKILL.md)
- Security threat models: [docs/security/threat-models/](docs/security/threat-models/)
- Architectural decisions log: [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md)
