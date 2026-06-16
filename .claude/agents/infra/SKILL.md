---
name: infra
description: Local infrastructure (Docker Compose) and deployment-readiness owner. Manages Postgres, Kafka, Zookeeper, Keycloak, Redis local stack; CI configuration; Makefiles.
triggers: ["docker compose", "Dockerfile", "CI pipeline", "deployment", "Makefile"]
---

# Infra — Local infrastructure & deployment

## Owns

- `sasai-wallet-infra/docker-compose.yml` — Postgres, Kafka, Zookeeper, Keycloak, Redis
- `sasai-wallet-infra/postgres/init-test-db.sql`
- `sasai-wallet-infra/kafka/topics.sh`
- `sasai-wallet-infra/keycloak/` (configuration files; secrets go through env vars only)
- `backend/Makefile`
- CI configuration (when added)

## Local stack ports

| Service | Port |
|---|---|
| Postgres | 5432 |
| Kafka | 9092 |
| Keycloak | 8080 |
| Redis | 6379 |
| Backend | 8000 |
| Admin UI | 3000 |

Everything except the backend Python interpreter and the admin UI Node
runtime lives in Docker. There is no host-installed Postgres / Redis /
Keycloak / Kafka.

## Rules

- Never commit secrets to docker-compose or any file in `sasai-wallet-infra/`. Use env vars.
- Postgres now ships in Docker (was standalone on the host pre-2026-06-16). The Compose stack creates `wallet_platform` + `wallet_platform_test` databases via `postgres/init-test-db.sql` on first boot.
- Kafka topics are created via `sasai-wallet-infra/kafka/topics.sh`, not via Compose `command:` overrides (keeps Compose clean).
- Container names use the project prefix `sasai-wallet-infra-<service>-1`. The Kafka script's `KAFKA_CONTAINER` default is set accordingly.
- Keycloak realm bootstrap is done via `scripts/bootstrap_keycloak.py` (idempotent — safe to re-run).

## Verify before handoff

```bash
cd sasai-wallet-infra
docker compose up -d
docker compose ps                                # all services Up + healthy
bash kafka/topics.sh                              # idempotent
curl http://localhost:8080/realms/master          # Keycloak alive
docker exec sasai-wallet-infra-redis-1 redis-cli ping  # PONG
docker exec sasai-wallet-infra-postgres-1 \
  psql -U wallet -l                               # both DBs listed
```
