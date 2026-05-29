---
name: scaffold-rule
description: Add a new rule type to the rules engine. Wires the evaluator branch, progress tracking, schema, and required test scenarios.
---

# /scaffold-rule

## Inputs

- Rule type name (must be one of the 7 in PRD §9: milestone, streak, first-time, value-based, composite, campaign, referral)
- The specific scenario it covers (if extending behaviour of an existing type)

## Outputs

- `backend/app/modules/rules/evaluators/{type}.py` — evaluator function
- `backend/app/modules/rules/schemas.py` — add fields specific to the rule type
- `backend/app/shared/models/rules.py` — add fields to `Rule` model if needed (then `/scaffold-model` flow for migration)
- `backend/tests/rules/test_{type}.py` — required scenarios:
  - fires when threshold met
  - does not fire when below threshold
  - idempotent re-evaluation (NFR-0110)
  - type-specific: streak break, composite AND vs OR, campaign date range, etc.
- `admin-ui/app/rules/forms/{Type}Form.tsx` — admin UI for configuring this rule type

## Verify

```bash
cd backend
pytest tests/rules/test_{type}.py -v
# Also run the broader idempotency invariant
pytest tests/invariants/test_no_double_issuance.py
```
