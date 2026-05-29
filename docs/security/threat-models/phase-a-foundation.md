# Threat Model — Phase A Foundation (Identity + Accounts + Ledger)

> **Date:** 2026-05-28
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0010 to 0240
> **Code reference:** `backend/app/modules/{identity,accounts,ledger}/`

---

## 1. What this phase delivers

Foundation models and minimal endpoints to:
- Register users (test-only — full OTP/PIN flow deferred to Phase 2)
- Resolve any identifier (phone/email/account/card) to canonical `user_id`
- Create wallet + points accounts including the new system issuance account
- Internal ledger service for double-entry writes (no public ledger endpoint yet)

This is the substrate on which P2P and rewards stand. Getting it wrong is hard to undo.

## 2. Data flow

```
[Test HTTP client]  --POST /users-->  [Identity API]
                                          ↓
                                     [User + UserIdentifier in DB]

[Test HTTP client]  --POST /accounts->  [Accounts API]
                                          ↓
                                     [Account row in DB]

[Internal caller]   --post_transaction-->  [Ledger Service]
                                          ↓
                                     [Transaction + LedgerEntry rows]
                                          ↓
                                     [SUM-to-zero invariant must hold]
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption (Phase A) |
|---|---|---|
| HTTP → API | JSON body | Pydantic v2 validates. **No auth in Phase A** — endpoints are tagged `test-only`. |
| API → DB | SQL via ORM | Tenant isolation enforced in WHERE clause. UUID PKs only. |
| Service → Ledger | Function calls | Caller responsible for double-entry balance. Service rejects unbalanced txns. |

> **Phase A explicit non-goal:** authentication. The endpoints are test-only and will be auth-gated in Phase 2. This is documented in code (router tags, docstrings) and in `MEMORY.md`.

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Caller fakes a `tenant_id` in request body | High (no auth) | High | `tenant_id` accepted in body for Phase A test endpoints ONLY; flagged with TODO; Phase 2 resolves from token | accepted (Phase A only) |
| T-1 | Tampering | Direct UPDATE on `ledger_entries` | Low (developer error only) | Critical | Code review + automation-testing invariant `test_ledger_sum_to_zero`; comment in model file | mitigated |
| R-1 | Repudiation | User denies registration | Low | Low | `users.created_at` immutable; no audit log in Phase A (deferred) | accepted (Phase A) |
| I-1 | Info disclosure | Phone number in error message | Med | Med | `mask_phone()` helper in `shared/utils/masking.py`; ruff lint rule for f-strings with PII names | mitigated |
| I-2 | Info disclosure | Cross-tenant read | High (no auth!) | Critical | Service-layer filter on `tenant_id`; **test_tenant_isolation** for every endpoint | mitigated by tests |
| D-1 | DoS | Unbounded identifier list per user | Low | Low | No explicit limit in Phase A; revisit if abuse seen | accepted |
| E-1 | Elevation | User upgrades own status field | High (no auth!) | High | Status not exposed in Phase A endpoints; only seeded via service | mitigated |

## 5. Project-specific tests required (handed to `automation-testing`)

- `test_create_user_rejects_duplicate_phone_in_same_tenant`
- `test_create_user_allows_same_phone_in_different_tenant`
- `test_resolve_identifier_returns_404_for_other_tenant`
- `test_create_account_rejects_unknown_tenant`
- `test_ledger_post_transaction_requires_balanced_entries`
- `test_ledger_sum_to_zero_invariant` (session-scoped)
- `test_ledger_entries_are_append_only` (attempted UPDATE → AssertionError in test)
- `test_overdraft_rejected_before_ledger_write` (Phase B has the real test; stub here)

## 6. Residual risks (accepted for Phase A)

- **No auth on test endpoints.** Acceptable because Phase A is local-dev only and we deliberately defer Keycloak integration to Phase 2 to keep iteration speed high. The risk is sealed by:
  - Endpoints tagged `test-only` in OpenAPI
  - No staging/prod deployment of Phase A code
  - Tracking issue: "Phase 2: gate all endpoints behind `get_current_user`/`get_current_admin`"
- **No audit log writes** for user/account creation. Re-introduced in Phase 2 alongside auth.

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Regression tests enumerated above (handed to automation-testing)
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-28
