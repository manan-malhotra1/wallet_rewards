.PHONY: dev test check seed lint format migrate migrate-new

dev:
	uvicorn app.main:app --reload --port 8000

test:
	pytest -v

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
