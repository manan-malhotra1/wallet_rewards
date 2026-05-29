---
paths:
  - "backend/**/*.py"
---

# Python backend conventions

## Imports

Order: stdlib → third-party → local. `ruff` enforces. Use absolute imports rooted at `app.`.

```python
# Good
from app.modules.users.service import resolve_identifier
# Bad
from ..users.service import resolve_identifier
```

## Type hints

- PEP 604 unions (`str | None`), not `Optional[str]`.
- Use `from __future__ import annotations` only when needed for forward refs — don't sprinkle it.
- Pydantic v2 `BaseModel` for all request/response schemas. No `dataclass` in API surface.

## Async

- Every route function is `async def`. Use `httpx.AsyncClient`, never `requests`.
- DB sessions are async (`AsyncSession`). Inject via `Depends(get_async_session)`.
- Background work goes to Celery, never `asyncio.create_task` for fire-and-forget.

## Error handling

- Raise custom exceptions from `shared/exceptions/`. They map to HTTP responses with `{"error_code": "...", "message": "..."}`.
- Never let stack traces escape to API consumers.
- Use `try/except` only where you can do something meaningful. Let unexpected errors bubble to the FastAPI exception handler.

## Logging

- Use `structlog`. No `print()`, no `logger.info(f"...")` with sensitive data interpolated.
- Bind context once at request entry: `log.bind(user_id=..., tenant_id=..., trace_id=...)`.
- Mask PII: `mask_phone(phone)`, `mask_email(email)` helpers in `shared/utils/`.

## Service / router split

- Routers contain NO business logic. They:
  1. Parse the request (Pydantic does this)
  2. Resolve auth dependencies
  3. Call exactly one service function
  4. Return the result (Pydantic serialises)
- Services do all DB queries, calls to other services, Kafka emits.

## Idempotency

Every state-mutating endpoint requires an `Idempotency-Key` header (Pay-PRD-0200). On duplicate, return the original response. Store in `transactions.idempotency_key` (UNIQUE per tenant).

## External calls

- Happen AFTER DB commit, never inside a transaction (NFR-0130).
- Wrap in `try/except httpx.TimeoutException` and update transaction to PENDING + log.
- Reconciliation job (Module 12) resolves PENDING.

## Tests

- `pytest` + `pytest-asyncio`.
- Every endpoint: happy path + at least one auth failure + at least one validation failure.
- Use real PostgreSQL (test DB), not SQLite — schema parity matters.
- Tenant isolation test for every domain endpoint.
