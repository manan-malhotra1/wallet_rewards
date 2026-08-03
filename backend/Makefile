.PHONY: dev worker beat flower test test-report check seed lint format migrate migrate-new

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Celery worker — executes background tasks (the reward-outbox reconciliation
# sweep). Run alongside `make dev` and `make beat`. Uses the same host `.env`
# as the app (REDIS_URL / DATABASE_URL point at the compose-forwarded ports).
worker:
	celery -A app.celery_app worker --loglevel=INFO

# Celery beat — periodic scheduler; enqueues `rewards.recon_sweep` every 60s
# (schedule lives in app/celery_app.py). Run exactly one beat process.
beat:
	celery -A app.celery_app beat --loglevel=INFO

# Flower — Celery monitoring dashboard at http://localhost:5555. Shows recon
# sweep run history/timings. Needs the worker started with `-E` (add it here:
# `make worker` → append `-E`) to populate live task events.
flower:
	celery -A app.celery_app flower --port=5555

test:
	pytest -v

# Run the suite with the report recorder on, then render the combined HTML
# report (test-reports/index.html). `|| true` so a failing run still reports.
test-report:
	SASAI_TEST_REPORT=1 pytest -q || true
	python ../scripts/build_test_report.py

check:
	ruff check .
	ruff format --check .
	mypy app/
	python ../scripts/check_migrations.py

lint:
	ruff check .

format:
	ruff format .

seed:
	python ../scripts/seed.py

migrate:
	alembic upgrade head

migrate-new:
	@read -p "Migration name: " name; \
	alembic revision --autogenerate -m "$$name"
