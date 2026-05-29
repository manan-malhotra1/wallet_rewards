---
name: migrate-db
description: Safe database migration. Generate, review, apply, verify.
---

# /migrate-db

## Inputs

- Description of the schema change (e.g. "add `activated_at` to `rules`")

## Workflow

1. Edit the model class(es) in `backend/app/shared/models/`.
2. `cd backend && alembic revision --autogenerate -m "description"`
3. **REVIEW** the generated migration. Alembic gets the following wrong often:
   - Enum value additions (manual `ALTER TYPE` needed)
   - Index changes (regenerates more aggressively than needed)
   - Default values (sometimes drops them)
   - Renaming columns (Alembic sees as drop + add — destructive!)
4. Edit the migration to be correct.
5. `alembic upgrade head`
6. `alembic downgrade -1 && alembic upgrade head` — verify both directions work
7. `python ../scripts/check_migrations.py`
8. Run the relevant invariant tests.

## Never

- Edit a migration that's been applied anywhere (dev / staging / prod). Write a corrective migration.
- Use `op.execute(raw_sql)` unless absolutely necessary. Prefer the Alembic ops API.
- Skip the docstring on the migration file.
- Commit a migration with the default `autogenerate` description — rewrite to be specific.

## When to escalate

- Rename of a column or table — these are destructive in Alembic by default. Discuss the migration strategy (rename + dual-write + backfill + drop) before applying.
- Type narrowing (e.g. `VARCHAR(255)` → `VARCHAR(100)`) — confirm no existing data violates the constraint.
- Dropping a column — confirm no production reads on it.
