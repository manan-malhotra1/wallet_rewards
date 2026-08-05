---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.sql"
---

# Fintech compliance rules

These rules govern every line of code in this repo. The compliance agent reviews PRs against this checklist.

## Credentials & PII

Never appear in logs, audit records, API responses, error messages, or database fields in plain form (NFR-0170):

- PIN — only stored as a bcrypt hash (via `backend/app/auth/hashing.py`, not passlib)
- OTP — only stored as a bcrypt hash
- Session tokens — Redis only, never in DB, never logged
- Full card numbers — never stored, only tokenised reference
- Full account numbers — stored, but masked in logs

PII (phone, email, account, card identifier) MUST be masked in application logs (NFR-0240):
- Phone: `+27 82 555 0142` → `+27 82 *** 0142`
- Email: `jane@example.com` → `j***@example.com`
- Account: `ZA-001-887-2210` → `ZA-001-***-2210`
- Card: `5234 5678 9012 3456` → `5234 **** **** 3456`

Use helpers in `backend/app/shared/utils/masking.py`. Never improvise.

## Audit trail (NFR-0160, NFR-0250)

Every administrator action goes to `audit_log` with:
- `actor_id` (user_id, admin Keycloak ID, or 'system')
- `actor_type` ('user' | 'admin' | 'system')
- `action` (e.g. 'rule.activated', 'user.suspended')
- `entity_type`, `entity_id`
- `before_state` JSONB
- `after_state` JSONB
- `ip_address`
- `created_at`

`audit_log` has NO `updated_at`. Entries are immutable. No automated process may delete from it.

State transitions on `transactions`, `redemptions`, and `user_rule_progress` are also audit-logged.

## Retention (NFR-0150)

| Table | Minimum retention |
|---|---|
| `ledger_entries`, `transactions` | 7 years |
| `audit_log` | 7 years |
| `security` events (auth_attempts) | 7 years |
| `otp_requests` | 30 days, then purge |
| `event_ingestion_log` | 90 days |

Retention is enforced by background purge jobs (Celery beat). The 7-year tables have no purge job — they grow.

## Tenant isolation (NFR-0220)

Every query against a domain table MUST filter by `tenant_id` from the session context.

A failing tenant isolation test is a PR blocker.

## Encryption in transit (NFR-0260)

All external calls (payment rails, redemption providers, event sources) over TLS 1.2+. No exceptions. No "internal" trust assumptions.

## External event integrity (Pay-PRD-0495)

Every external event source must be registered. Every event from a registered source must carry verifiable proof-of-origin. Failures are rejected and audit-logged with source identifier + timestamp + reason.

## Auth & session (NFR-0180, NFR-0190, NFR-0280)

- Session inactivity timeout: ≤ 5min USSD, ≤ 15min mobile.
- Failed PIN/OTP attempts trigger lockout (configurable threshold + duration).
- New session on same channel invalidates earlier session for the same user.

## Fraud signal (NFR-0270)

If a user's reward issuance volume in 24h exceeds the configured threshold, flag for Administrator review. Do NOT auto-block in Phase 1 — flag only.

## Out of scope (Phase 1, but ON the roadmap)

- KYC / AML transaction monitoring (limits + thresholds only in Phase 1)
- PCI scope (no card data stored — only tokenised refs)
- SOC 2 / ISO 27001 controls documentation
- Sanctions screening

When any of these is requested, this file moves it from "Phase 1 deferred" to "Phase 2 active" — update accordingly.
