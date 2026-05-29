---
name: scaffold-event-consumer
description: Generate a new Kafka consumer with idempotent processing, event_ingestion_log check, and matching test.
---

# /scaffold-event-consumer

## Inputs

- Topic name (must be a constant in `app/config.py:Topics`)
- Consumer group name suffix
- Per-event handler logic description

## Outputs

- `backend/app/modules/{module}/consumer.py` — consumer class
- Registration in `app/main.py` startup
- `backend/tests/{module}/test_{topic}_consumer.py` — happy path + duplicate handling + integrity failure

## Pattern

```python
class FooConsumer(BaseConsumer):
    topic = Topics.SOMETHING
    group_id = "wallet-platform.foo.something"

    async def handle(self, event: NormalisedEvent, session: AsyncSession) -> None:
        # 1. Check event_ingestion_log for (source_key, external_event_id)
        # 2. If present: no-op, return
        # 3. Process the event
        # 4. Insert event_ingestion_log row with status='PROCESSED'
        # 5. If failure: status='FAILED' + reason
```

## Rules

- MUST be idempotent (Pay-PRD-0500)
- On rejection: write to `event_ingestion_log` + `audit_log`, never raise to caller
- Long-running work goes to Celery, not inside `handle()`
- Consumer group naming: `wallet-platform.{service}.{topic-suffix}`

## Verify

```bash
cd backend
pytest tests/{module}/ -k consumer -v
```
