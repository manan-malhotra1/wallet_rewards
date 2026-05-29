# Threat Model — Phase B P2P Transfers

> **Date:** 2026-05-28
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0250 to 0320 (Module 4 — Payment Orchestration)
> **Code reference:** `backend/app/modules/payments/`

---

## 1. What this phase delivers

- `POST /api/v1/payments/p2p` — atomic peer-to-peer transfer between two users' financial wallets in the same tenant.
- Overdraft prevention before any ledger write (Pay-PRD-0220).
- Idempotency keyed by header (Pay-PRD-0200).
- Recipient resolved by registered identifier (Pay-PRD-0060).
- A new `system_cash_inflow` account type so the seed can give Alice/Bob opening ZAR balances via double-entry top-ups.

**Deferred to later phases:** real auth (still no Keycloak), limits checks (Pay-PRD-0330–0360), pricing (Pay-PRD-0390–0400), bill-pay, public top-up endpoint.

## 2. Data flow

```
[Test HTTP client]
   |
   |  POST /api/v1/payments/p2p
   |  Idempotency-Key: <uuid>
   |  Body: { tenant_id, sender_user_id, recipient_identifier, amount, currency }
   v
[Payments router]  ──> [Payments service]
                          |
                          |  1. resolve recipient (identity service)
                          |  2. find sender + recipient wallets
                          |  3. SELECT FOR UPDATE on sender wallet (lock)
                          |  4. derive available balance
                          |  5. overdraft check
                          v
                       [Ledger service: post_transaction]
                          |   DEBIT sender_wallet
                          |   CREDIT recipient_wallet
                          v
                       [transactions + ledger_entries written]
                       [lock released on commit]
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption (Phase B) |
|---|---|---|
| HTTP → API | JSON body + Idempotency-Key header | Pydantic v2 validates. **No auth in Phase B** — endpoints tagged `test-only`. |
| Service → Identity service | Resolves recipient identifier | Function call, both modules run in-process. |
| Service → Ledger service | Balanced entries | Ledger re-validates the balance and idempotency before writing. |
| Service → Postgres | Locking SELECT FOR UPDATE | Row lock held until DB transaction commits. |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Attacker submits `sender_user_id` of another user | High (no auth) | Critical | Accepted residual risk for Phase B — endpoint flagged test-only; Phase 2 resolves sender from token | accepted |
| T-1 | Tampering | Replay same Idempotency-Key with different body to alter recipient | Med | High | Idempotency check returns the ORIGINAL transaction regardless of new body — second request gets first response, no new side effect | mitigated |
| T-2 | Tampering | Manipulate ledger entries directly | Low | Critical | Append-only via service; invariant test catches drift | mitigated |
| R-1 | Repudiation | Sender denies a transfer | Low (no auth) | Low | `transactions.initiated_by` recorded; full audit log deferred to Phase 2 | accepted |
| I-1 | Info disclosure | Recipient identifier in URL/body leaks via logs | Med | Med | `mask_phone()` etc. helpers available; logging wiring in Phase 2 | mitigated by convention |
| I-2 | Info disclosure | Cross-tenant transfer leaks recipient existence | High | Med | Recipient resolution is tenant-scoped → 404 user_not_found | mitigated |
| D-1 | DoS | Spam P2P with tiny amounts | Med | Low | No rate limit in Phase B — limits engine (Pay-PRD-0330) lands in a later phase | accepted |
| D-2 | DoS | Concurrent same-Idempotency-Key requests cause lock contention | Low | Low | `post_transaction` catches IntegrityError race and returns existing | mitigated |
| E-1 | Elevation | Caller spoofs `sender_user_id` to transfer from anyone | High (no auth) | Critical | Same as S-1 — accepted Phase B residual | accepted |

## 5. Project-specific test scenarios (handed to `automation-testing`)

Mandatory tests for Phase B:

1. **Happy path** — Alice 1000 → Bob 0, P2P 100. Result: Alice 900, Bob 100.
2. **Overdraft rejected** — Alice 100 → Bob 0, P2P 200. Result: 409, balances unchanged.
3. **Currency mismatch** — Alice ZAR wallet, recipient has only USD wallet. 422 / 404 / 409 (test what we settle on — `currency_mismatch`).
4. **Self-transfer rejected** — Alice → Alice. Result: 422 self_transfer_not_allowed.
5. **Recipient not found** — phone unknown. Result: 404 user_not_found.
6. **Sender wallet not found** — sender user exists but has no wallet in this currency. Result: 404 account_not_found.
7. **Cross-tenant transfer rejected** — recipient identifier exists only in Tenant B; request is in Tenant A. Result: 404 (no existence leak).
8. **Idempotent replay** — same key, same body → same transaction id, balances stable.
9. **Idempotent replay (different body)** — same key, different recipient → returns ORIGINAL transaction (Pay-PRD-0200 semantics).
10. **Concurrent double-spend** — two simultaneous transfers of full balance. Only ONE succeeds; the other gets 409 overdraft. (Tested via two awaited tasks against the same wallet — the `SELECT FOR UPDATE` serialises them.)
11. **Zero / negative amount rejected** — 422.
12. **Tenant isolation on response** — request tenant A but accounts ID in tenant B → 404.
13. **`ledger_sum_to_zero` invariant** after a series of P2P transfers — still zero.

## 6. New account type — `system_cash_inflow`

Following the same pattern as `system_points_issuance` (Phase A addendum), this is the
debit-side account when money arrives FROM outside the system (top-ups, external receipts).

Without this, the seed script can't give Alice/Bob opening balances via double-entry —
and P2P is uninteresting without balances to move.

- One `system_cash_inflow` account per (tenant, currency).
- Balance trends negative as more cash flows in. The negative number equals
  total user-held cash + reserved balances.
- Future top-up endpoint (Pay-PRD-0320) will use this account.

## 7. Residual risks (accepted for Phase B)

- **No auth.** Same as Phase A — endpoint flagged test-only.
- **No limits/pricing.** PRD's orchestration sequence (Pay-PRD-0260) is partially implemented — only the ledger step. Roles + limits + pricing land later. Documented as TODOs in the service code with the relevant PRD reference.
- **No rate limiting.** A single test client could spam the endpoint. Acceptable for local dev.

## 8. Sign-off

- [x] STRIDE pass complete
- [x] Regression tests enumerated
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-28
