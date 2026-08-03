# Backend image — used by the Celery worker + beat services in
# sasai-wallet-infra/docker-compose.yml. The FastAPI app itself still runs on
# the host via `make dev`; this image exists so the background workers (the
# reward-outbox reconciliation sweep) run alongside the rest of the local
# stack without a host-installed Celery.
#
# The recon sweep only needs the app package + its Python deps and a route to
# Postgres/Redis (supplied via compose `environment:` overrides). Source is
# bind-mounted over /app in compose for live-reload parity with `make dev`.
FROM python:3.12-slim

WORKDIR /app

# Install deps first so the layer caches across source edits. confluent-kafka
# and asyncpg ship manylinux wheels, so no system build toolchain is needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baked-in copy so the image runs standalone; compose bind-mounts ../backend
# over this for local dev.
COPY . .

# Default to the worker; the beat service overrides `command` in compose.
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=INFO"]
