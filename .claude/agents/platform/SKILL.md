---
name: platform
description: Keycloak auth, Kafka topics, tenant config, and cross-cutting infra glue inside the backend. Owns identity dependencies, JWT validation, event source registration, and Kafka producer/consumer wiring.
triggers: ["Keycloak", "JWT", "Kafka topic", "tenant config", "event source registration", "consumer setup"]
---

# Platform — Auth, Kafka, tenancy

## Owns

- Keycloak integration: `backend/app/dependencies.py` (`get_current_user`, `get_current_admin`)
- Kafka wiring: `backend/app/modules/events/` infrastructure (producer factory, consumer base class, topic constants)
- Tenant resolution dependency: `get_current_tenant()`
- `infra/keycloak/realm-export.json`
- Kafka topics shell script: `infra/kafka/topics.sh`

## Does NOT own

- Application logic in event modules (that's **backend** + **rules-engine**)
- Docker Compose itself (that's **infra**)

## Reference

- Tech architecture §4 (auth) and §3 (Kafka topics)

## Rules

- Topic names live as constants in `app/config.py`. Never hardcode strings.
- Every consumer is idempotent — check `event_ingestion_log` before processing (Pay-PRD-0500).
- Every producer emits AFTER DB commit, never inside a transaction.
- Partition key = `user_id` always.
- Keycloak public keys cached in-memory with 24h TTL for JWT verification.
- Service-account flow (`backend-service` client) for backend → Keycloak admin API calls.
- External event source authentication (Pay-PRD-0495): verify proof-of-origin, reject + audit-log failures.

## Verify before handoff

```bash
# Topic creation
bash infra/kafka/topics.sh
# Keycloak realm import
# (manual in admin console at http://localhost:8080)
# Auth dependency
pytest backend/tests/auth/
```
