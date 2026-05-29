---
name: commit
description: Pre-commit gate. Runs lint, type check, alembic check, unit tests, then commits with a conventional-commit message.
---

# /commit — pre-commit gate

## Steps

1. `git status` — show changes
2. `git diff` — show staged + unstaged
3. Backend gate (if backend/ touched):
   - `cd backend && ruff check . && ruff format --check .`
   - `mypy app/`
   - `python ../scripts/check_migrations.py`
   - `pytest` (fast subset; full suite in CI)
4. Admin UI gate (if admin-ui/ touched):
   - `cd admin-ui && npm run lint`
   - `npm run build`
5. Draft commit message — conventional commits:
   - `feat(rules): add streak rule evaluator`
   - `fix(payments): release reservation on external timeout`
   - `chore: bump httpx`
6. Confirm with user; commit; show `git status` after.

## Never

- Skip the gate (`--no-verify`) unless user explicitly authorises.
- Amend a published commit. Always create new.
- `git add -A` blindly — list files explicitly.
- Commit `.env`, secrets, or any file matching `.env*` (except `.env.example`).
