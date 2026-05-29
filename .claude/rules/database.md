---
paths:
  - "backend/app/shared/models/**"
  - "backend/alembic/**"
  - "backend/app/database.py"
---

# Database conventions

## SQLAlchemy 2.0 style

- Use `Mapped[...]` annotations and `mapped_column()`. Never the legacy `Column()` declaration style.
- Use `select(Model).where(...)` — never `session.query(Model).filter(...)`.
- Async session everywhere. `await session.execute(stmt)`, `result.scalar_one_or_none()`, etc.

```python
# Good
from sqlalchemy.orm import Mapped, mapped_column
class User(Base):
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
```

## Universal column conventions

- `id`: UUID PK, `gen_random_uuid()` default
- `tenant_id`: UUID FK to `tenants.id`, indexed, on every domain table
- `created_at`, `updated_at`: `TIMESTAMPTZ`, default `now()`
- `deleted_at`: `TIMESTAMPTZ NULL` for soft-delete tables
- Money / points: `NUMERIC(20, 6)`, currency in separate `CHAR(3)` column

## Indexes

Every FK gets an index. Every column used in WHERE or ORDER BY gets an index. Composite indexes for the common multi-column filter (e.g. `(tenant_id, status, created_at DESC)`).

## Constraints

- `CHECK` constraints for enums (e.g. `CHECK (status IN ('PENDING', 'COMPLETED', ...))`).
- `UNIQUE` constraints for natural keys (e.g. `(tenant_id, identifier_type, identifier_value)`).
- `NOT NULL` by default. Only `NULL`-able when the absence is meaningful.

## Migrations

- Filename: `YYYYMMDD_NNNN_description.py`
- Every migration has a one-line docstring describing the change.
- Generated migrations: review the SQL before applying. Alembic gets enums and indexes wrong.
- **NEVER edit an already-applied migration.** Write a corrective new one.
- Down-migrations should work when feasible; if not, document why in the docstring.
- Run `python scripts/check_migrations.py` (which wraps `alembic check`) before every commit.

## Ledger-specific

- `ledger_entries` has NO `updated_at`. Entries are immutable.
- Reversal = new entry, never `UPDATE`.
- The application MUST NOT issue `UPDATE` against `ledger_entries`. Enforce with a code review checklist + a SQL audit linter (TODO).

## Tenant isolation

- Every query against a domain table MUST filter by `tenant_id` from the session context.
- TODO: implement a SQLAlchemy event hook to auto-inject the tenant filter — currently it's manual discipline.
- Tests must include cross-tenant read attempts that should return zero rows.
