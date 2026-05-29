---
paths:
  - "backend/app/modules/events/**"
  - "backend/app/modules/engagement/**"
---

# Kafka producer / consumer rules

## Topics

Defined as constants in `app/config.py`. Never hardcode topic name strings elsewhere.

```python
# app/config.py
class Topics:
    TRANSACTIONS_COMPLETED = "wallet.transactions.completed"
    EVENTS_EXTERNAL        = "wallet.events.external"
    EVENTS_NORMALISED      = "wallet.events.normalised"
    REWARDS_ISSUED         = "wallet.rewards.issued"
    ENGAGEMENT_OUTBOUND    = "wallet.engagement.outbound"
    RECONCILIATION_PENDING = "wallet.reconciliation.pending"
```

## Partition key

ALWAYS `user_id`. This preserves per-user event order (a streak rule must see events in chronological order for a given user). Cross-user ordering is not preserved by design.

## Producers

- Emit AFTER the DB transaction is committed. NEVER inside a transaction.
- Pattern:

```python
# Wrong — emit inside transaction
async with session.begin():
    await session.execute(stmt)
    await producer.send(topic, event)  # can succeed even if commit fails

# Right — emit after commit
async with session.begin():
    await session.execute(stmt)
# Transaction committed at this point
await producer.send(topic, event)
```

- If the emit fails AFTER commit: log loud, push to an outbox table for retry. Do NOT try to roll back the DB change.
- Outbox pattern: when we add it, the producer writes a row to `event_outbox` inside the same transaction; a background worker drains the outbox and emits to Kafka with retries.

## Consumers

- MUST be idempotent. Before processing any event, check `event_ingestion_log` for `(source_key, external_event_id)`. If present, no-op.
- On successful processing: insert into `event_ingestion_log` with `status='PROCESSED'`.
- On failure: insert with `status='FAILED'` + `failure_reason`. Do not retry inline — the dead-letter approach is to write to a DLQ topic and surface in admin UI for manual review.
- Consumer groups are named `wallet-platform.{service}.{topic}`.

## External event integrity (Pay-PRD-0495)

Before passing any externally-sourced event to the rules engine:

1. Verify `source_key` exists in `external_event_sources` and `status='active'`.
2. Verify proof-of-origin (HMAC signature, mutual TLS, or signed JWT — depending on source contract).
3. On failure: drop the event, write to `event_ingestion_log` with `status='REJECTED'` and `failure_reason='integrity_check_failed'`. Add an `audit_log` entry with the source identifier.

## Schema

All events follow a standard schema (Pay-PRD-0490):

```json
{
  "event_id": "uuid",
  "tenant_id": "uuid",
  "user_id": "uuid",
  "transaction_type": "string",
  "amount": "decimal",
  "currency": "ZAR",
  "merchant_id": "uuid|null",
  "source_key": "string",
  "timestamp": "ISO-8601 UTC",
  "raw": { ... }
}
```

External events go through `events/normaliser.py` (mapping via `external_event_sources.field_mapping JSONB`) before reaching this schema.

## Performance

- Rules engine evaluation per event: target < 500ms (NFR-0050).
- Don't do synchronous external calls inside a consumer. Hand off to Celery for any long-running work.
