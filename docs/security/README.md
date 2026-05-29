# Security Documentation

Owned by the [`security`](../../.claude/agents/security/SKILL.md) agent.

## Structure

| Path | Purpose |
|---|---|
| `threat-models/` | One STRIDE threat model per feature touching auth / money / PII. Use `_template.md`. |
| `vapt-reports/` | VAPT findings, dated. Format defined in `.claude/agents/security/SKILL.md`. |
| `playbook.md` | Incident response runbook + quarterly sweep checklist. |

## When to add a threat model

Before coding starts for any module touching:
- Authentication / session / OTP / PIN
- The ledger or any money/points movement
- External integrations (payment providers, redemption providers, event sources)
- PII fields
- Admin-only destructive actions (suspend, reverse, manual reconcile)

## When to add a VAPT report

- After completing a feature in the categories above (pre-commit)
- After every quarterly sweep
- After every security incident
- On user request

## Cross-references

- Coding guidelines: [.claude/rules/coding-guidelines.md](../../.claude/rules/coding-guidelines.md)
- Compliance rules: [.claude/rules/compliance-fintech.md](../../.claude/rules/compliance-fintech.md)
- Ledger invariants: [.claude/rules/ledger-invariants.md](../../.claude/rules/ledger-invariants.md)
- Security agent SKILL: [.claude/agents/security/SKILL.md](../../.claude/agents/security/SKILL.md)
