# Threat Model — <Feature Name>

> **Status:** Template — copy to `<feature>.md` and fill in.
> **Date:** YYYY-MM-DD
> **Reviewer:** security agent
> **PRD reference:** Pay-PRD-XXXX (and any NFR-XXXX)
> **Code reference:** `backend/app/modules/<module>/...`

---

## 1. What this feature does

<2–3 sentences. Plain English. The flow from user/system input to side effects.>

## 2. Data flow

```
<ASCII diagram of how data moves through this feature, including the trust boundaries>

Example:
[Mobile App] --HTTPS--> [FastAPI: /api/v1/payments/p2p]
                          ↓
                        [PaymentService.transfer()]
                          ↓
                        [DB: transactions + ledger_entries]
                          ↓ (after commit)
                        [Kafka: wallet.transactions.completed]
                          ↓
                        [External: Mobile money provider]
```

## 3. Trust boundaries

| Boundary | What crosses it | Trust assumption |
|---|---|---|
| Browser → API | Request body + JWT | JWT verified, body re-validated |
| API → DB | SQL via ORM | ORM prevents injection; tenant_id enforced in WHERE |
| API → Kafka | Message payload | Signed/sequenced if cross-system |
| API → External | HTTPS request | TLS 1.2+, response re-validated |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | <e.g. attacker presents another user's JWT> | Med | High | Keycloak signature verify; iss/aud/exp checked | open / fixed / accepted |
| T-1 | Tampering | <e.g. modify request body to change recipient> | Low | High | Pydantic validation; tenant_id from token, not body | |
| R-1 | Repudiation | <e.g. user denies initiating a transfer> | Low | Med | audit_log entry with actor + IP + before/after | |
| I-1 | Info disclosure | <e.g. error response leaks DB ID format> | Med | Low | Generic error messages; PII masked in logs | |
| D-1 | DoS | <e.g. flood /p2p with payloads, exhaust DB connections> | Med | Med | Rate limit per user; max body size | |
| E-1 | Elevation | <e.g. support-agent calls platform-admin endpoint> | Low | High | Role check in dependency; 403 on mismatch | |

## 5. Project-specific threats (cross-reference `.claude/agents/security/SKILL.md` §C)

For features touching the ledger / payments / redemption / rewards:

- [ ] Tenant isolation bypass attempted on every endpoint?
- [ ] Idempotency replay tested with different bodies same key?
- [ ] Double-spend race tested with concurrent identical requests?
- [ ] If reward flow: double-issuance race tested via Kafka replay?
- [ ] If external integration: spoofed source signature tested?

## 6. Residual risks (accepted with justification)

- <Threat ID + brief reason for acceptance. e.g. "D-1 accepted for Phase 1 — rate limiting deferred until first scale incident. Mitigation: monitor `kafka_consumer_lag` and add throttle if breached.">

## 7. Required regression tests

Handed to [`automation-testing`](../../../.claude/agents/automation-testing/SKILL.md) agent for permanent coverage:

- `test_<feature>_rejects_cross_tenant_access`
- `test_<feature>_idempotent_on_duplicate_key`
- `test_<feature>_<other-specific-scenario>`

## 8. Sign-off

- [ ] All open Critical / High mitigated or accepted with justification
- [ ] Regression tests written and passing
- [ ] PRD references cited
- [ ] Reviewed by: __________ on __________
