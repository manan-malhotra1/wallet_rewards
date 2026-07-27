.PHONY: dev test test-report check seed lint format migrate migrate-new

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

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
