---
name: infra
description: Local infrastructure (Docker Compose) and deployment-readiness owner. Manages Kafka, Zookeeper, Keycloak, Redis local stack; CI configuration; Makefiles.
triggers: ["docker compose", "Dockerfile", "CI pipeline", "deployment", "Makefile"]
---

# Infra — Local infrastructure & deployment

## Owns

- `infra/docker-compose.yml` — Kafka, Zookeeper, Keycloak, Redis
- `infra/kafka/topics.sh`
- `infra/keycloak/` (configuration files; secrets go through env vars only)
- `backend/Makefile`
- CI configuration (when added)

## Local stack ports

| Service | Port |
|---|---|
| Kafka | 9092 |
| Keycloak | 8080 |
| Redis | 6379 |
| PostgreSQL | 5432 (local, not Docker) |
| Backend | 8000 |
| Admin UI | 3000 |

## Rules

- Never commit secrets to docker-compose or any file in `infra/`. Use env vars.
- Local PostgreSQL stays outside Docker — easier to inspect with `psql`. We'll containerise for staging/prod.
- Kafka topics are created via `infra/kafka/topics.sh`, not via Compose `command:` overrides (keeps Compose clean).
- Keycloak realm import is one-time manual step — document in README.

## Verify before handoff

```bash
cd infra
docker compose up -d
docker compose ps      # all services Up
bash kafka/topics.sh   # idempotent
curl http://localhost:8080/realms/master  # Keycloak alive
redis-cli ping         # PONG
```
