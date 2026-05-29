# Security Playbook

> **Owner:** [`security`](../../.claude/agents/security/SKILL.md) agent
> **Status:** Living document — update after every incident or sweep.

---

## 1. Reporting channels

- **Internal finding (developer or operator):** open a private issue tagged `security` (when repo is on GitHub). For now: note in `docs/security/vapt-reports/`.
- **External finding (researcher disclosure):** TBD — publish a `SECURITY.md` with PGP-encrypted email when going public.

---

## 2. Triage severity

| Severity | Definition | Response SLA |
|---|---|---|
| Critical | Active exploitation possible, no mitigation, leaks money/PII | Drop everything. Patch within 24h. |
| High | Exploitable, leaks money/PII, mitigation exists | Patch within 72h. |
| Medium | Exploitable under non-default config OR no money/PII impact | Patch within 2 weeks. |
| Low | Minor info disclosure, no business impact | Patch in next sprint. |
| Info | Hardening suggestion, no vulnerability | Backlog. |

---

## 3. Incident response runbook (Phase 1, local-only)

This will expand significantly once we have staging/prod. For now:

1. **Identify** — does the issue allow money movement, PII leak, or auth bypass?
2. **Contain** — stop the relevant docker compose service if it's actively exploited
   (`docker compose stop <service>`). Local-only, so blast radius is limited.
3. **Eradicate** — patch the code, run `automation-testing` regression, verify with
   `security` agent.
4. **Document** — write up the incident in `docs/security/vapt-reports/YYYY-MM-DD-incident-<name>.md`.
5. **Learn** — update threat model. Add the exploit as a permanent regression test.

---

## 4. Quarterly sweep checklist

Run at the start of Mar / Jun / Sep / Dec:

- [ ] `pip-audit --strict` (backend)
- [ ] `npm audit --audit-level=moderate` (admin-ui)
- [ ] `gitleaks detect --source .`
- [ ] `bandit -r backend/app/`
- [ ] Run the 15 fintech-specific test scenarios in `.claude/agents/security/SKILL.md` §C
- [ ] Verify each external integration's TLS certificate and webhook secret are current
- [ ] Review all `audit_log` actions for the quarter — flag anomalous patterns
- [ ] Output: `docs/security/vapt-reports/YYYY-Q<n>-quarterly.md`

---

## 5. Pre-deploy checklist (for when staging/prod exists)

TBD — to be filled in when we add the deployment automation.
