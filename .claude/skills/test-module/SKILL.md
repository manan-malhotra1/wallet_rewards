---
name: test-module
description: Run tests for a specific module, report coverage, diagnose failures.
---

# /test-module

## Inputs

- Module name (e.g. `rules`, `accounts`, `payments`)

## Workflow

1. `cd backend && pytest tests/{module}/ -v --cov=app/modules/{module}`
2. If failures: read the failing test names, hypothesise root cause, propose fix (don't apply yet).
3. Show coverage report. If < 80% line coverage on the module, list uncovered lines and propose tests.
4. Always run the invariant suite afterwards: `pytest tests/invariants/`.

## Never

- Skip failing tests with `pytest.mark.skip` without user approval.
- Lower coverage threshold to make a check pass.
- Mock production code paths (services) just to get a test green. If you can't test a code path without mocking it, the code likely has the wrong shape.
