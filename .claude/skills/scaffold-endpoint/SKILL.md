---
name: scaffold-endpoint
description: Generate a new FastAPI endpoint with router, schemas, service function, dependency-injected tenant-scoped DB query, and test file.
---

# /scaffold-endpoint

## Inputs

- Module name (e.g. `rules`, `accounts`)
- HTTP verb + path (e.g. `POST /api/v1/rules/{rule_id}/activate`)
- Request/response shape

## Outputs

- `backend/app/modules/{module}/router.py` — add route, no business logic
- `backend/app/modules/{module}/service.py` — add service function, all logic here
- `backend/app/modules/{module}/schemas.py` — add Pydantic v2 request/response models
- `backend/tests/{module}/test_{action}.py` — happy path + auth fail + validation fail + tenant isolation

## Defaults

- Async route function
- `Depends(get_async_session)` for DB
- `Depends(get_current_admin)` or `get_current_user` for auth
- `Idempotency-Key` header required if state-mutating
- 422 on validation, 401 on auth, 403 on permission, 404 on not-found, 409 on conflict
- Returns `{"error_code": "...", "message": "..."}` on errors

## Verify

```bash
cd backend
ruff check . && mypy app/
pytest tests/{module}/ -v
```
