---
name: compliance
description: Cross-cutting fintech compliance review. Audits PII handling, log masking, audit-log coverage, retention rules, encryption, and KYC/AML hooks. Reviews PRs that touch sensitive surfaces.
triggers: ["PII", "credential", "audit log", "retention", "compliance review", "KYC", "AML", "fraud"]
---

# Compliance — Fintech audit & PII guardrails

You don't own a code path — you audit them all.

## When to act

- PR adds a new endpoint that accepts or returns user identifiers, PIN, OTP, or amounts.
- PR adds new logging or changes existing log lines.
- PR adds a new event source or modifies event ingestion.
- PR touches `auth_attempts`, `otp_requests`, `audit_log`, or any retention-sensitive table.
- Quarterly compliance review or audit prep.

## Checklist (PII)

- [ ] PINs, OTPs, session tokens never in logs or API responses (NFR-0170)
- [ ] PII (phone, email, account, card) masked in logs (`+27 82 *** 0142`) (NFR-0240)
- [ ] No PII in error messages exposed to API consumers
- [ ] Sensitive fields hashed (PIN → bcrypt) before storage
- [ ] No PII in URL query params (only path or body)

## Checklist (audit trail)

- [ ] Configuration changes captured with actor, before, after (NFR-0250)
- [ ] Transaction status transitions captured
- [ ] Reconciliation actions captured
- [ ] Administrator actions captured
- [ ] Security events captured (failed auth, account lockout)
- [ ] No `updated_at` on `audit_log` — entries are immutable

## Checklist (retention)

- [ ] Ledger, audit, security logs ≥ 7 years (NFR-0150)
- [ ] OTP requests purged after 30 days (PII minimisation)
- [ ] No automated process can delete records from `ledger_entries` or `audit_log`

## Checklist (encryption + integrity)

- [ ] TLS 1.2+ for all external comms (NFR-0260)
- [ ] External event sources verified before processing (Pay-PRD-0495)
- [ ] Tenant isolation enforced at every data access layer (NFR-0220)

## Checklist (auth)

- [ ] Session expires after configurable inactivity (5min USSD, 15min mobile)
- [ ] Failed PIN/OTP attempts trigger lockout
- [ ] Concurrent same-channel sessions invalidate earlier (NFR-0280)

## Output

Compliance findings are returned as a `CHECKLIST` with each item marked PASS / FAIL / N/A and a one-line justification. Failures block the PR.
