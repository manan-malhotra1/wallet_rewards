---
name: scan-security
description: OWASP-focused security scan on a code change before deploying anything sensitive.
---

# /scan-security

Run before any change that touches: auth, ledger, redemption, external API calls, or PII handling.

## Checklist

### Authentication & session
- [ ] Endpoint enforces auth via `Depends(get_current_user)` or `get_current_admin)` — no anonymous access unless intentional (registration, OTP send)
- [ ] No `user_id` accepted in request body — always resolved from auth token
- [ ] Session expiry honoured

### Authorisation
- [ ] Role check for sensitive operations (suspend, reverse, manual resolution)
- [ ] Tenant isolation: cross-tenant access returns 404 / 403, never leaks data

### Input validation
- [ ] All inputs go through Pydantic schemas (no raw dict reads)
- [ ] String fields have max length
- [ ] Numeric fields have min/max bounds
- [ ] Enum fields use Python `Enum`, not free string

### Secrets & PII
- [ ] No secrets, keys, or passwords in code, logs, or error messages
- [ ] PII masked in all logs (NFR-0240)
- [ ] No PIN, OTP, session token in logs or responses (NFR-0170)
- [ ] No PII in URL query params (only path / body)

### Injection
- [ ] No raw SQL — SQLAlchemy ORM only
- [ ] No `eval()`, `exec()`, dynamic import
- [ ] No shell command construction from user input
- [ ] CSRF tokens on state-mutating server actions (Next.js handles by default for server actions)

### Idempotency & state
- [ ] State-mutating endpoint requires `Idempotency-Key`
- [ ] Ledger entries never UPDATE'd
- [ ] Status transitions enforced (no PENDING after COMPLETED)

### External calls
- [ ] TLS 1.2+ for every external call
- [ ] External event sources verified before processing (Pay-PRD-0495)
- [ ] Timeouts configured (default 30s)
- [ ] Calls happen AFTER DB commit, never inside transaction

### Audit
- [ ] Sensitive action triggers an `audit_log` entry
- [ ] Audit entry has actor, before/after state

## Output

Findings as `PASS / FAIL / N/A`. Failures are PR blockers.
