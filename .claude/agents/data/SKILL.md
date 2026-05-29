---
name: data
description: Database layer owner. Writes SQLAlchemy ORM models, Alembic migrations, query optimisations, and enforces ledger invariants at schema level.
triggers: ["add model", "alembic migration", "schema change", "ledger entry", "balance query"]
---

# Data — Database & ledger owner

## Owns

- `backend/app/shared/models/` — SQLAlchemy ORM, one file per domain
- `backend/alembic/` — migration management
- `backend/app/database.py` — engine + session factory
- Schema definitions, indexes, constraints

## Module pattern

One file per domain in `shared/models/`:

- `tenants.py` — `Tenant`, `TenantConfig`
- `users.py` — `User`, `UserIdentifier`, `UserProfile`, `OtpRequest`, `AuthAttempt`
- `accounts.py` — `Account`, `AccountBalanceSnapshot`
- `ledger.py` — `Transaction`, `LedgerEntry`
- ... one file per Technical PRD §6 sub-section

## Rules

- UUID PKs (`gen_random_uuid()`) on every table.
- `TIMESTAMPTZ` everywhere, never `TIMESTAMP`.
- Soft delete via `deleted_at TIMESTAMPTZ NULL` — never hard delete.
- `tenant_id` on every domain table.
- Money / points = `NUMERIC(20, 6)` — never float.
- Every FK gets an index.
- No triggers, no stored procedures.
- All schema changes via Alembic. **Never write DDL directly.**

## Ledger invariants (non-negotiable)

- `ledger_entries` has NO `updated_at`. Entries are immutable. Reversal = new entry.
- Every transaction produces ≥ 2 ledger entries (one DEBIT + one CREDIT).
- System-wide sum of ledger entries = 0 (NFR-0100). Add to `tests/invariants/`.
- `transactions.idempotency_key` UNIQUE per tenant.

## Migration discipline

```bash
# After model change:
alembic revision --autogenerate -m "description"
# Review generated SQL — Alembic gets things wrong, especially on enum + index changes
alembic upgrade head
python scripts/check_migrations.py
```

- Filename: `YYYYMMDD_NNNN_description.py`
- Every migration has a one-line docstring.
- NEVER edit a migration that's been applied anywhere. Write a corrective one.
- Down-migrations should work when feasible; if not, document why in the docstring.

## Verify before handoff

```bash
python scripts/check_migrations.py
pytest backend/tests/invariants/
```
