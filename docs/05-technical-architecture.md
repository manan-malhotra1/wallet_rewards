# Technical Architecture

> System-level summary — the authoritative per-module implementation is in [docs/design/](design/README.md); requirements are in [docs/02-prd.md](02-prd.md). Last refreshed 2026-08-05.

> **Document type:** Technical Architecture
> **Version:** 0.2 (refreshed against `main`)
> **Date:** 2026-05-28 · refreshed 2026-08-05

This is a system-level quick-reference. For per-module HOW (money core, maker-checker, rewards, events, tenancy), read the design docs under [docs/design/](design/README.md). For requirements and acceptance criteria, read the [Product PRD](02-prd.md).

---

## 1. Tech stack (locked)

| Layer | Tech | Version |
|---|---|---|
| Backend language | Python | 3.12 |
| Backend framework | FastAPI | 0.136.3 |
| ORM | SQLAlchemy | 2.0.50 |
| Migrations | Alembic | 1.18.4 |
| Database | PostgreSQL | local |
| Message broker | Apache Kafka | local (Docker Compose) |
| Identity (admin) | Keycloak | local (Docker Compose) |
| Admin UI | Next.js (App Router) + next-auth v5 | 16.2.6 |
| Mobile app | Expo (SDK 54) · React Native · expo-router · Tamagui | **built** (Phase 2 promoted) |
| Runtime | Node.js | 22.22.2 |
| Package manager | npm | 10.9.7 |
| Task queue | Celery + Redis | latest |
| API validation | Pydantic v2 | latest |
| Admin auth | Keycloak JWT (RS256/JWKS) | Docker |
| User auth | Custom PIN/OTP + Redis sessions + step-up PIN | — |
| HTTP client | httpx | latest |
| Kafka client (Py) | confluent-kafka | latest |

---

## 2. System architecture

The backend is a **modular monolith** (one deployable, one folder per domain under `backend/app/modules/`) — ~27 modules. Two clients: the Next.js **Admin UI** (Keycloak JWT) and the **Expo mobile app** (PIN/OTP + Redis session). Per-tenant `business_type` (`wallet` / `rewards` / `both`) is the master switch for which subsystems are live.

```
        ┌────────────────────┐        ┌────────────────────┐
        │   Admin UI         │        │   Mobile app       │
        │ (Next.js 16, :3000)│        │ (Expo / RN)        │
        └─────────┬──────────┘        └─────────┬──────────┘
                  │ Bearer JWT (Keycloak)       │ PIN/OTP + Redis session
                  └───────────────┬─────────────┘
                                  ▼
┌────────────────────┐  ┌────────────────────────────┐  ┌─────────────────┐
│  External event    │─▶│  Backend (FastAPI, :8000)  │◀▶│  PostgreSQL     │
│  sources (rewards  │  │  Modular monolith, ~27     │  │  (ledger,       │
│  mode only)        │  │  modules. Money core:      │  │   reward_outbox)│
└────────────────────┘  │   identity, accounts,      │  └─────────────────┘
         │              │   ledger (post_transaction │
         │ Kafka        │   choke point), payments,  │  ┌─────────────────┐
         │ (external    │   cashin/cashout/airtime,  │◀▶│  Redis          │
         │  ingest only)│   pin_change, treasury,    │  │ (sessions,      │
         ▼              │   limits, pricing, taxes,  │  │  Celery, cache) │
┌────────────────────┐  │   commissions, roles,      │  └─────────────────┘
│  Kafka (Docker)    │─▶│   step_up, redemption,     │
│  wallet.events.    │  │   reconciliation.          │  ┌─────────────────┐
│  external          │  │  Rewards: events, rules,   │◀─│  Keycloak       │
└────────────────────┘  │   rewards, segments,       │  │  (admin auth)   │
                        │   budgets, catalog.        │  └─────────────────┘
                        │  Governance: config_/money_│
                        │   /user_operations.        │
                        │  Platform: tenants,        │
                        │   instruments, services,   │
                        │   external, api_keys,      │
                        │   analytics, audit.        │
                        └────────────┬───────────────┘
                                     │ after commit
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
   ┌────────────────────┐  ┌──────────────────┐  ┌────────────────────┐
   │ reward_outbox      │  │ Redemption       │  │ Airtime providers  │
   │ (internal wallet→  │  │ providers        │  │ (async vend +      │
   │  rewards, `both`)  │  │ (Mukuru, MTN…)   │  │  callback)         │
   └────────────────────┘  └──────────────────┘  └────────────────────┘
```

Wallet→rewards coupling in `both` mode is an in-DB **transactional outbox** (`reward_outbox`), NOT Kafka. Kafka is used **only** for inbound external event ingestion in `rewards` mode. See [design/06-events-ingestion-and-mode-awareness.md](design/06-events-ingestion-and-mode-awareness.md).

---

## 3. Deployment modes (`tenants.business_type`)

A per-tenant enum — three values, load-bearing (resolved in `backend/app/shared/tenant_mode.py`):

| Mode | Wallet money paths | Rewards from wallet activity | External Kafka events |
|---|---|---|---|
| `wallet` | live | none issued | rejected (`wrong_mode`) |
| `rewards` | rewards-only | — | **only** event source |
| `both` | live | via internal transactional **outbox** | rejected (`wrong_mode`) |

Replaces the old two-value `wallet` / `rewards_only`.

---

## 4. Kafka topics

Only **one** topic is live: external ingestion. The engagement-emission topics are reserved config with no producer yet (Module 17 gap).

| Topic | Producer | Consumer | Status |
|---|---|---|---|
| `wallet.events.external` | External partners (rewards mode) | Ingestion consumer (`scripts/run_consumer.py`) | **live** |
| `wallet.rewards.issued` | — | — | reserved, no producer (Module 17 gap) |
| `wallet.engagement.outbound` | — | — | reserved, no producer (Module 17 gap) |

**Partition key = `user_id`** (preserves per-user event order). Internal wallet→rewards does **not** use Kafka — it uses the `reward_outbox` table drained by a post-commit fast path + a 60s Celery sweep.

---

## 5. Module pattern

Every module under `backend/app/modules/{module}/` has:

```
modules/
├── identity/
│   ├── __init__.py
│   ├── router.py     # FastAPI APIRouter — routes only, no logic
│   ├── service.py    # All business logic, DB queries
│   └── schemas.py    # Pydantic v2 request/response models
```

`ledger`, `audit`, and `admin_profiles` are **service-only** (no router). Shared:
- `shared/models/` — SQLAlchemy ORM, one file per domain (e.g. `users.py`, `ledger.py`)
- `shared/tenant_mode.py` — the single `business_type` reader (mode gating)
- `shared/exceptions/` — all custom exceptions in one file (~100 classes, all subclass `AppHTTPException`)
- `shared/utils/` — helpers (PII masking, identifier normalisation, user-type resolution)
- `app/auth/` — Keycloak JWT, Redis sessions, bcrypt hashing, HMAC callbacks, API-key + rate-limit

Being a modular monolith, in-process money flows call services directly through the `post_transaction` choke point; cross-domain rewards coupling goes through the `reward_outbox` table, not direct imports. Inbound partner events arrive over Kafka/HTTP.

---

## 5a. Money core — one choke point, one guard

**Every** value movement (P2P, cash-in/out, airtime, change-PIN fee, redemption, treasury fund/withdraw/adjust, external partner fund/withdraw/merchant-cashin, reward issuance/cashback) funnels through a single function: `ledger.service.post_transaction`. Nothing writes ledger entries any other way. It enforces (full detail in [design/02-ledger-accounts-and-money-movement.md](design/02-ledger-accounts-and-money-movement.md)):

- **Append-only ledger** — reversals append opposite-direction legs; balance = `SUM(ledger_entries)`.
- **Idempotency first** — unique `(tenant_id, idempotency_key)`; a duplicate key returns the original result.
- **The `FOR UPDATE` balance guard** (the M-01 fix) — only `financial_wallet` and the `system_cash_inflow` cash float are guarded (all pool/collection/points accounts skipped); guarded rows are locked in id-sorted order before any balance read, held through commit. Enforces overdraft rejection (`InsufficientFunds` / `InsufficientFloat`), the `max_balance` ceiling on user-wallet credits, and the non-negative cash-float floor. Reversals + earned payouts are cap-exempt.
- **Fail-closed pricing + limits** — before any ledger write, `require_pricing_and_limits` requires BOTH a pricing AND a limit config to resolve for the acting user's type, else `422` (Pay-PRD-0420). No silent zero-fee/limitless pass-through.
- **External calls after commit only** (NFR-0130) — airtime/redemption reserve PENDING, dispatch after commit, settle on callback/sweep.

Standard per-transaction order: `assert_user_can_transact → require_permission → assert_service_allowed → require_pricing_and_limits → check_limits + wallet send/receive caps → enforce_step_up → assemble_charges → post_transaction → external call`.

## 5b. Governance — maker-checker

Three parallel maker-checker subsystems share one shape (propose → PENDING → approve / request-changes → revise/resubmit/withdraw → apply-on-approval in one transaction), surfaced to admins as a single unified `/approvals` inbox. No self-approval; N-eyes needs N distinct approvers; apply uses a deterministic idempotency key. Detail: [design/04-maker-checker-and-approvals.md](design/04-maker-checker-and-approvals.md).

| Subsystem | Governs | Checker role |
|---|---|---|
| `config_requests` | pricing / limit / wallet-limit / tax / commission / step-up config | config-approver |
| `money_operations` | treasury fund / withdraw / adjust-float / bank-mirror (N-eyes) | treasury-approver |
| `user_operations` | admin create / edit user (four-eyes) | user-approver |

---

## 6. API surface

`/api/v1/{module}/` for each module (~93 endpoints across ~27 routers). Registered in `app/main.py`. Full per-module tables in [docs/design/](design/README.md).

| Area | Base path(s) | Key endpoints |
|---|---|---|
| Identity + `/me` | `/api/v1/identity` | `POST /users`, `POST /otp/send`, `POST /otp/verify`, `POST /pin/set`, `POST /auth/pin`, `GET /resolve`, `GET /me/wallet`, `GET /me/rewards` |
| Accounts | `/api/v1/accounts` | `POST ` , `GET /{id}/balance` |
| Money paths (user) | `/api/v1/{payments,cashin,cashout,airtime,pin}` | `POST /p2p`, `POST /cashin`, `POST /cashout`, `POST /airtime/recharge`, `POST /pin/change` (all idempotency-keyed) |
| Treasury (operator) | `/api/v1/treasury` | `POST /fund-user`, `POST /withdraw`, `POST /adjust-system-wallet`, `POST /bank-mirrors` (governed via money-operations) |
| Money controls | `/api/v1/{limits,pricing,taxes,commissions,step-up,budgets}` | read `GET /configs`; writes go through config-requests |
| Roles / services / instruments | `/api/v1/{roles,services,instruments}` | RBAC + service access policy + currency catalog CRUD |
| Redemption / recon | `/api/v1/{redemption,reconciliation}` | `POST /initiate`, `POST /{id}/callback`, `GET /pending`, `POST /sweep` |
| Rewards / rules / segments | `/api/v1/{rules,segments,catalog,events}` | rule CRUD, segment membership, `/me` catalog, `POST /events/external` |
| Governance | `/api/v1/{config-requests,money-operations,user-operations}` | `POST ` propose, `POST /{id}/approve`, `POST /{id}/request-changes`, `PATCH /{id}`, `POST /{id}/resubmit`, `POST /{id}/withdraw` |
| Platform | `/api/v1/{tenants,api-keys,external,analytics}` | tenant CRUD + branding, partner API-key mint, partner money API (API-key auth), per-currency analytics |

---

## 7. Auth model

**Admin / operator** — Keycloak realm `wallet-platform`, client `admin-ui` (Confidential, OIDC code flow). Backend validates Keycloak JWT (RS256/JWKS) via `require_admin_role(...)` → `AdminPrincipal`. Realm roles: `platform-admin`, `config-approver`, `user-approver`, `treasury-approver`, `finance-reviewer`, `support-agent`.

**End user (mobile / USSD)** — Custom in `app/modules/identity/`: phone + PIN, OTP verification at registration. PIN stored as bcrypt hash. **Redis session tokens** (sliding TTL) issued after PIN auth, validated via `get_current_user()`. High-value transactions require a **step-up PIN** (`enforce_step_up`, fail-closed).

**Partner / external** — per-tenant API keys (`require_api_key` → `ApiKeyPrincipal`) with rate limiting; provider callbacks (airtime, redemption) authenticated by **HMAC** `X-Sasai-Signature`.

**Backend-to-Keycloak** — `backend-service` client (service account, client credentials flow) for user-admin API calls into Keycloak.

---

## 8. Database management

All schema changes via Alembic. No direct DDL.

```bash
# After model change:
alembic revision --autogenerate -m "description_of_change"
alembic upgrade head

# Verify models in sync with schema:
python scripts/check_migrations.py
```

- All tables UUID PK (`gen_random_uuid()`)
- All timestamps `TIMESTAMPTZ`
- Soft deletes via `deleted_at TIMESTAMPTZ NULL`
- Migration files named `YYYYMMDD_NNNN_description.py`
- Every migration has a one-line docstring

CI runs `alembic check` before any deploy.

---

## 9. Local development

```bash
# 1. Infra (Postgres, Kafka, Keycloak, Redis — all in Docker)
cd sasai-wallet-infra && docker compose up -d
bash kafka/topics.sh
python ../scripts/bootstrap_keycloak.py   # provisions realm + clients

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload --port 8000

# 3. Admin UI
cd admin-ui
npm install
npm run dev      # :3000
```

---

## 10. Environment variables

**Backend (`backend/.env`)**
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/wallet_platform
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
REDIS_URL=redis://localhost:6379/0
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=wallet-platform
KEYCLOAK_CLIENT_ID=backend-service
KEYCLOAK_CLIENT_SECRET=<from keycloak>
SECRET_KEY=<random 64-char hex>
OTP_EXPIRY_SECONDS=300
PIN_MAX_ATTEMPTS=5
PIN_LOCKOUT_MINUTES=30
```

**Admin UI (`admin-ui/.env.local`)**
```
NEXT_PUBLIC_APP_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=wallet-platform
KEYCLOAK_CLIENT_ID=admin-ui
KEYCLOAK_CLIENT_SECRET=<from keycloak>
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<random 32-char hex>
```

---

## 11. Compliance posture (Phase 1)

| Concern | Approach |
|---|---|
| PII | PINs/OTPs/tokens never logged; `passlib` for PIN hash; PII masked in app logs (NFR-0240) |
| Data retention | 7-year retention on ledger, audit, security logs (NFR-0150) |
| Audit trail | Every config change, status transition, reward issuance, security event (NFR-0160, NFR-0250) |
| Encryption in transit | TLS 1.2+ for all external comms (NFR-0260) |
| Tenant isolation | `tenant_id` on every domain table, resolved from token at every request (NFR-0220) |
| KYC / AML | Out of scope Phase 1; KYC status tracked, AML deferred (OQ-08) |
| Event source authentication | Registered sources only, proof-of-origin verified, failures audit-logged (Pay-PRD-0495) |
