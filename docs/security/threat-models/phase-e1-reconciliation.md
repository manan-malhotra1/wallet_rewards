# Threat Model — Phase E.1 Reconciliation

> **Date:** 2026-05-29
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0750 to 0800 (Module 12) + Pay-PRD-0710 (timeout handling)
> **Code reference:** `backend/app/modules/reconciliation/`

---

## 1. What this phase delivers

Closes the "no reconciliation sweep" residual risk carried forward from Phase D.

- `audit_log` table (PRD §6.13) — generic immutable audit trail, used here for
  reconciliation actions; will be reused by every state-changing endpoint in
  Phase F.
- Reconciliation module:
  - `POST /api/v1/reconciliation/sweep` — find PENDING redemptions older than a
    threshold, bump retry_count, escalate to MANUAL_REVIEW after max_retries
    (Pay-PRD-0750, 0790).
  - `GET /api/v1/reconciliation/pending` — list PENDING items eligible for sweep.
  - `GET /api/v1/reconciliation/manual-review` — list MANUAL_REVIEW redemptions
    needing operator attention.
  - `POST /api/v1/reconciliation/{redemption_id}/resolve` — operator manually
    resolves MANUAL_REVIEW to COMPLETED or REVERSED.
  - `GET /api/v1/reconciliation/audit` — read the audit trail (filterable).

Deferred:
- Actual external provider `status_check_url` call (Pay-PRD-0720) — Phase F.
  In E.1 the sweep just bumps retry_count; real status-check polling needs
  HMAC-verified callback infra.
- Celery beat scheduling — manual trigger via HTTP endpoint for now.
- Tenant-configurable thresholds — passed as request param in E.1.

## 2. Data flow

```
[Operator / cron]                          [Operator]
   |                                          |
   |  POST /sweep {threshold_minutes: 60}     |  POST /{id}/resolve {outcome, reason}
   v                                          v
[Reconciliation.sweep_pending]             [Reconciliation.manually_resolve]
   |                                          |
   |  1. Find PENDING redemptions             |  1. Find MANUAL_REVIEW redemption
   |     older than cutoff                    |  2. Flip ledger entries:
   |  2. For each:                            |       PENDING -> COMPLETED or REVERSED
   |       - increment retry_count            |  3. Update redemption status terminal
   |       - if retry_count >= max_retries:   |  4. Write audit_log entry
   |           status = MANUAL_REVIEW         |
   |       - else: just update last_checked   |
   |       - write audit_log entry            |
   v                                          v
[transactions + redemptions + audit_log]   [transactions + redemptions + audit_log]
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption (Phase E.1) |
|---|---|---|
| HTTP → API | JSON body | Pydantic validates. **No auth** — endpoints flagged test-only. |
| Service → Redemption row | redemption_id from path | Tenant scope re-checked; manual-resolve requires MANUAL_REVIEW status |
| Service → audit_log | INSERT-only, no UPDATE/DELETE | Append-only by convention; no `updated_at` column |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Caller spoofs operator identity to manually resolve in another user's favour | High (no auth) | High | Accepted residual — endpoints test-only; Phase F resolves actor from token | accepted |
| T-1 | Tampering | Operator manually completes a redemption that should have failed (free money) | Med | Critical | audit_log captures actor + before/after state; Phase F adds role check requiring `finance-reviewer` or higher | partial |
| T-2 | Tampering | Sweep accidentally bumps retry on a COMPLETED transaction | Low | Low | Query filters by status='PENDING' explicitly; test covers it | mitigated |
| R-1 | Repudiation | Operator denies a manual resolution action | Low | Med | audit_log immutable, captures actor_id + timestamp + before/after | mitigated |
| I-1 | Info disclosure | Audit log queries leak cross-tenant entries | Med | Med | Tenant filter on every audit query | mitigated |
| D-1 | DoS | Operator triggers sweep with threshold=0, sweeping every single item | Low | Low | Tests catch it; minimum threshold validation; rate limiting in Phase G | accepted |
| E-1 | Elevation | Support-agent role manually resolves redemptions to COMPLETED | High (no role check) | Critical | Phase F enforces finance-reviewer+ for resolve; audit log evidence trail | accepted |

## 5. Project-specific test scenarios

1. **Sweep bumps retry_count for stale PENDING** — redemption older than threshold gets retry_count++.
2. **Sweep ignores recent PENDING** — within threshold = no change.
3. **Sweep ignores COMPLETED / REVERSED** — only PENDING is candidate.
4. **Sweep escalates after max_retries** — retry_count >= provider.max_retries → MANUAL_REVIEW.
5. **Sweep writes audit_log entries** — one per item processed.
6. **Manual resolve to COMPLETED** — flips ledger entries to COMPLETED, balance permanently drops.
7. **Manual resolve to REVERSED** — flips ledger to REVERSED, balance restored.
8. **Manual resolve rejects non-MANUAL_REVIEW** — 409.
9. **Manual resolve cross-tenant** — 404.
10. **List pending tenant-scoped** — no cross-tenant leak.
11. **Audit log immutability** — no `updated_at` column on the table.
12. **Audit log tenant-isolated** — query for tenant A returns only tenant A entries.

## 6. Residual risks accepted for Phase E.1

- No auth on any endpoint
- No role-based gating on manual resolve (any caller can complete or reverse)
- No real provider status-check call (sweep is a retry-counter bump only)
- No scheduled sweep — manual trigger only via HTTP

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Regression test list handed to automation-testing
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-29
