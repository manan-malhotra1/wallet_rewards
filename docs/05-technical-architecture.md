# Technical Architecture

> **Document type:** Technical Architecture
> **Version:** 0.1 (distillation of Technical PRD v1.0)
> **Date:** 2026-05-28
> **Source of truth:** `/Users/manan/Downloads/wallet-platform-technical-prd-v1_0.md`

This is a local quick-reference. For full schemas, API tables, and per-folder `.claude.md` content, see the source Technical PRD.

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
| Admin UI | Next.js | 16.2.6 |
| Runtime | Node.js | 22.22.2 |
| Package manager | npm | 10.9.7 |
| Task queue | Celery + Redis | latest |
| API validation | Pydantic v2 | latest |
| Auth middleware | python-jose + passlib | latest |
| HTTP client | httpx | latest |
| Kafka client (Py) | confluent-kafka | latest |

---

## 2. System architecture

```
                    ┌────────────────────┐
                    │   Admin UI         │
                    │ (Next.js 16, :3000)│
                    └─────────┬──────────┘
                              │ Bearer JWT (Keycloak)
                              ▼
┌────────────────────┐  ┌────────────────────────────┐  ┌─────────────────┐
│  External event    │─▶│  Backend (FastAPI, :8000)  │◀▶│  PostgreSQL     │
│  sources           │  │                            │  └─────────────────┘
│  (bank, MM, ptnr)  │  │   17 modules:              │
└────────────────────┘  │   identity, accounts,      │  ┌─────────────────┐
         │              │   ledger, payments,        │◀▶│  Redis          │
         │ Kafka        │   limits, pricing,         │  │  (Celery + cache)│
         ▼              │   roles, events, rules,    │  └─────────────────┘
┌────────────────────┐  │   rewards, redemption,     │
│  Kafka (Docker)    │◀─│   reconciliation,          │  ┌─────────────────┐
│  6 topics          │  │   segments, catalog,       │◀─│  Keycloak       │
└────────────────────┘  │   notifications, tenants,  │  │  (admin auth)   │
         │              │   engagement               │  └─────────────────┘
         │              └────────────┬───────────────┘
         │                           │
         ▼                           ▼
┌────────────────────┐      ┌──────────────────────┐
│  WebEngage         │      │  Redemption providers│
│  (engagement)      │      │  (Mukuru, MTN, etc.) │
└────────────────────┘      └──────────────────────┘
```

---

## 3. Kafka topics

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `wallet.transactions.completed` | Payment orchestrator | Rules engine, Engagement | Internal txn events |
| `wallet.events.external` | External partners | Event normaliser | Inbound external events |
| `wallet.events.normalised` | Event normaliser | Rules engine | Standardised event stream |
| `wallet.rewards.issued` | Reward issuer | Engagement, Notifications | Reward events |
| `wallet.engagement.outbound` | Engagement emitter | WebEngage connector | All outbound engagement |
| `wallet.reconciliation.pending` | Payment orchestrator | Reconciliation job | PENDING txns to sweep |

**Partition key = `user_id`** for every topic (preserves per-user event order).

---

## 4. Module pattern

Every module under `backend/app/modules/{module}/` has:

```
modules/
├── identity/
│   ├── __init__.py
│   ├── router.py     # FastAPI APIRouter — routes only, no logic
│   ├── service.py    # All business logic, DB queries, Kafka emits
│   └── schemas.py    # Pydantic v2 request/response models
```

Shared:
- `shared/models/` — SQLAlchemy ORM, one file per domain (e.g. `users.py`, `ledger.py`)
- `shared/schemas/` — Pydantic types shared across modules
- `shared/exceptions/` — Custom `HTTPException` subclasses
- `shared/utils/` — Helpers (hashing, pagination, token gen)

Cross-module communication via **events** (Kafka), never direct service imports.

---

## 5. API surface

`/api/v1/{module}/` for each module. Registered in `app/main.py`.

| Module | Base path | Key endpoints |
|---|---|---|
| Identity | `/api/v1/identity` | `POST /register`, `POST /otp/send`, `POST /otp/verify`, `POST /pin/set`, `POST /auth/pin`, `GET /resolve/{identifier}` |
| Accounts | `/api/v1/accounts` | `POST /`, `GET /{account_id}/balance`, `GET /{account_id}/transactions` |
| Payments | `/api/v1/payments` | `POST /p2p`, `POST /bill-pay`, `POST /top-up` |
| Redemption | `/api/v1/redemption` | `POST /initiate`, `GET /{redemption_id}/status` |
| Rules | `/api/v1/rules` | `POST /`, `GET /`, `PATCH /{rule_id}`, `DELETE /{rule_id}` |
| Segments | `/api/v1/segments` | `POST /`, `POST /{segment_id}/upload`, `GET /` |
| Catalog | `/api/v1/catalog/{user_id}` | `GET /summary`, `GET /points-history`, `GET /badges`, `GET /challenges`, `GET /nudges` |
| Tenants | `/api/v1/tenants` | `POST /`, `GET /`, `PATCH /{tenant_id}`, `POST /{tenant_id}/config` |
| Reconciliation | `/api/v1/reconciliation` | `GET /pending`, `POST /sweep`, `PATCH /{transaction_id}/resolve` |

---

## 6. Auth model

**Admin / operator** — Keycloak realm `wallet-platform`, client `admin-ui` (Confidential, OIDC code flow). Backend validates Keycloak JWT via dependency `get_current_admin()`. Roles defined in Keycloak: `platform-admin`, `finance-reviewer`, `support-agent`.

**End user (USSD / mobile)** — Custom in `app/modules/identity/`: phone + PIN, OTP verification at registration. PIN stored as bcrypt hash. Session tokens issued after PIN auth, validated via `get_current_user()`.

**Backend-to-Keycloak** — `backend-service` client (service account, client credentials flow) for user-admin API calls into Keycloak.

---

## 7. Database management

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

## 8. Local development

```bash
# 1. Infra
cd infra && docker compose up -d
bash kafka/topics.sh
# Open http://localhost:8080 → import keycloak/realm-export.json

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

## 9. Environment variables

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

## 10. Compliance posture (Phase 1)

| Concern | Approach |
|---|---|
| PII | PINs/OTPs/tokens never logged; `passlib` for PIN hash; PII masked in app logs (NFR-0240) |
| Data retention | 7-year retention on ledger, audit, security logs (NFR-0150) |
| Audit trail | Every config change, status transition, reward issuance, security event (NFR-0160, NFR-0250) |
| Encryption in transit | TLS 1.2+ for all external comms (NFR-0260) |
| Tenant isolation | `tenant_id` on every domain table, resolved from token at every request (NFR-0220) |
| KYC / AML | Out of scope Phase 1; KYC status tracked, AML deferred (OQ-08) |
| Event source authentication | Registered sources only, proof-of-origin verified, failures audit-logged (Pay-PRD-0495) |
