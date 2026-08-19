# Repo-root orchestration. Backend/admin-ui have their own Makefile/package.json;
# this file wires cross-stack tasks like the combined test report.
.PHONY: report report-backend report-frontend report-e2e report-html

# Full combined HTML report: run backend + frontend suites (with result
# recording on), then render test-reports/index.html. `|| true` keeps going on
# test failures — a failing run is exactly what the report is meant to surface.
# E2E (Playwright) is NOT part of `report` because it needs the live stack
# (backend + Keycloak + admin dev server) — run `make report-e2e` separately.
report: report-backend report-frontend report-html

# Backend: pytest with the report recorder enabled (writes test-reports/backend-run.json).
report-backend:
	cd backend && SASAI_TEST_REPORT=1 pytest -q || true

# Frontend: vitest JSON reporter (writes test-reports/frontend-run.json).
report-frontend:
	cd admin-ui && npm run test:report --silent || true

# E2E: Playwright JSON reporter (writes test-reports/e2e-run.json), then render.
# Needs the live stack up (see admin-ui/e2e/README.md).
report-e2e:
	cd admin-ui && PLAYWRIGHT_JSON_OUTPUT_NAME=../test-reports/e2e-run.json \
		npx playwright test --reporter=json || true
	python3 scripts/build_test_report.py

# Render the combined report from whatever run files already exist. Fast — no
# tests run — so it's the target to use while iterating on the report layout.
report-html:
	python3 scripts/build_test_report.py
