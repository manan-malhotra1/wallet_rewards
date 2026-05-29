---
name: scaffold-model
description: Generate a SQLAlchemy 2.0 ORM model plus matching Alembic migration plus tenant isolation test.
---

# /scaffold-model

## Inputs

- Domain (e.g. `rules`, `accounts`)
- Table name
- Columns + types + constraints

## Outputs

- `backend/app/shared/models/{domain}.py` — add model class with `Mapped[...]` typing
- `backend/alembic/versions/YYYYMMDD_NNNN_create_{table}.py` — generated migration (review SQL!)
- `backend/tests/models/test_{table}_tenant_isolation.py` — verifies cross-tenant reads return zero rows

## Mandatory columns on every domain table

- `id: UUID` primary key, `gen_random_uuid()` default
- `tenant_id: UUID` FK to `tenants.id`, indexed
- `created_at`, `updated_at`: `TIMESTAMPTZ`, default `now()`
- `deleted_at: TIMESTAMPTZ | None` if soft-deletable

## Workflow

1. Draft the model class.
2. `cd backend && alembic revision --autogenerate -m "create_{table}"`
3. Review the generated migration SQL — Alembic often gets enums + indexes wrong.
4. `alembic upgrade head`
5. `python ../scripts/check_migrations.py` — must pass.
6. Run the tenant isolation test.
