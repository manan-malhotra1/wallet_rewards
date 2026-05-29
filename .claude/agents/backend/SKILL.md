---
name: backend
description: FastAPI module owner. Writes routers, services, Pydantic schemas, dependencies, and module-level business logic. Excludes rules-engine module (owned by rules-engine agent) and DB models (owned by data agent).
triggers: ["add endpoint", "write FastAPI route", "add service function", "Pydantic schema"]
---

# Backend — FastAPI module owner

## Owns

- `backend/app/modules/{identity,accounts,ledger,payments,limits,pricing,roles,events,rewards,redemption,reconciliation,segments,catalog,notifications,tenants,engagement}/`
- `backend/app/shared/schemas/`, `backend/app/shared/exceptions/`, `backend/app/shared/utils/`
- `backend/app/main.py`, `backend/app/config.py`, `backend/app/dependencies.py`

## Does NOT own

- `backend/app/modules/rules/` — owned by **rules-engine** agent
- `backend/app/shared/models/` — owned by **data** agent
- `backend/alembic/` — owned by **data** agent
- Kafka topic configuration — owned by **platform** agent

## Module pattern (mandatory)

```
modules/{name}/
├── __init__.py
├── router.py     # FastAPI APIRouter, routes only
├── service.py    # Business logic, DB queries, Kafka emits
└── schemas.py    # Pydantic v2 request/response models
```

Routers contain NO business logic. They call service functions only.

## Rules

- All DB access via async SQLAlchemy session injected through `get_async_session()`.
- Never trust `user_id` from request body — always resolve from `get_current_user()` / `get_current_admin()` dependency.
- Every state-mutating endpoint requires an `Idempotency-Key` header (Pay-PRD-0200).
- HTTP errors return `{"error_code": "...", "message": "..."}`. Use custom subclasses in `shared/exceptions/`.
- Never expose stack traces to API consumers.
- Kafka emit happens AFTER DB commit, never inside a transaction.
- External HTTP calls (httpx) happen AFTER DB commit (NFR-0130).

## Verify before handoff

```bash
make check      # ruff + mypy + alembic check
make test
```

## Escalate to lead when

- The endpoint requires a new ledger entry pattern → also pull in data agent.
- The endpoint requires a Kafka topic that doesn't yet exist → pull in platform agent.
- The endpoint exposes PII or financial figures that aren't currently in the schema → pull in compliance agent.
