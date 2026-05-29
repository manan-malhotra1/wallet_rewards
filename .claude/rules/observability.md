---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
---

# Observability conventions

## Logging — backend

- `structlog` with JSON output in production.
- No `print()`. No `logger.info(f"hello {user_id}")` — context goes through structured fields, not f-strings.
- Bind context at request entry:

```python
log = structlog.get_logger().bind(
    request_id=request_id,
    user_id=user.id,
    tenant_id=tenant.id,
)
log.info("payment_initiated", amount=amount, currency=currency)
```

- **Never log:** PINs, OTPs, session tokens, full card numbers, full account numbers.
- **Mask PII:** `mask_phone("+27 82 555 0142") → "+27 82 *** 0142"`. Use the helper in `shared/utils/masking.py`.
- **Amounts**: log full amount with currency. Amounts are not PII.

## Logging — frontend

- Use the browser console sparingly. In production, route errors to Sentry (Phase 2).
- Never log a user identifier or token at info-level.
- Server actions: emit a structured log on every action invocation with `{action, user_id, tenant_id, success}`.

## Metrics

Phase 1: Prometheus exposition at `/metrics` (Phase 2 setup; not blocking MVP).

Key metrics when added:
- `http_request_duration_seconds` (histogram, by route + status)
- `kafka_consumer_lag` (per topic + partition)
- `ledger_entries_created_total` (counter, by entry_type + status)
- `rule_evaluations_total` (counter, by rule_type + outcome)
- `redemption_pending_count` (gauge)

## Traces

OpenTelemetry-ready: inject `trace_id` into the structlog context at request entry. Phase 2 will wire to a collector.

## Alert thresholds (defaults — refine after baseline)

| Signal | Threshold |
|---|---|
| `http_request_duration_seconds{quantile=0.95}` > 2s for 5min | warn |
| Kafka consumer lag > 1000 messages | warn |
| `ledger_sum_to_zero` invariant test failing | page (critical) |
| Redemption PENDING > 100 | warn |
| Fraud signal threshold breach (NFR-0270) | warn |

## What to add to every error log

- `request_id`
- `user_id` (if known — never log raw identifier)
- `tenant_id`
- `error_code` (matches the API error_code response)
- `error_message`
- `stack_trace` (server-side only, never in API response)

## Audit log vs application log

Two different things — don't conflate.

- **Application log** — operational telemetry, ephemeral, can be sampled.
- **Audit log** — `audit_log` table, immutable, 7-year retention, captures every config change and state transition. Never just rely on app logs for compliance evidence.
