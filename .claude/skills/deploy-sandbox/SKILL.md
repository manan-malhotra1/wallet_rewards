---
name: deploy-sandbox
description: Build images, push to registry, apply to sandbox namespace, smoke-test. (Phase 2 — staging/prod automation; placeholder for now.)
---

# /deploy-sandbox

> **Status:** Placeholder. Local Docker Compose is the only deployment in Phase 1. Staging/prod automation comes in Phase 2.

## Phase 1 workflow (local only)

```bash
# Bring up the local stack (Postgres, Kafka, Keycloak, Redis — all in Docker)
cd sasai-wallet-infra && docker compose up -d
bash kafka/topics.sh
python ../scripts/bootstrap_keycloak.py   # provisions realm + clients

# Apply DB migrations
cd ../backend && alembic upgrade head

# Start backend
uvicorn app.main:app --reload --port 8000 &

# Start admin UI
cd ../admin-ui && npm run dev &

# Smoke
curl http://localhost:8000/healthz
curl http://localhost:3000
```

## Phase 2 (placeholder — to be filled when staging exists)

1. Build images:
   ```bash
   docker build -t sasai-wallet/backend:$(git rev-parse --short HEAD) backend/
   docker build -t sasai-wallet/admin-ui:$(git rev-parse --short HEAD) admin-ui/
   ```
2. Push to registry
3. Apply Helm chart to sandbox namespace
4. Run smoke tests via the deployed admin UI URL
5. Roll back automatically if smoke fails

## Never

- Deploy without running `/scan-security` first if the change touches sensitive surfaces.
- Skip migrations (`alembic upgrade head`) on deploy.
- Deploy with uncommitted changes.
