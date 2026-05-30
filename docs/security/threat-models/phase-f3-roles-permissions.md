# Threat Model — Phase F.3 Per-user Roles & Permissions (Module 7)

> **Date:** 2026-05-30
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0440 to 0470 · Pay-PRD-0260 step 1
> **Code reference:** `backend/app/modules/roles/`, integration in `payments/`, `redemption/`
> **Linear:** WAL-46

---

## 1. What this phase delivers

Per-user platform roles (Module 7) — **distinct from Keycloak realm roles**.
Keycloak roles gate operator/admin endpoints; platform roles gate which
*transaction types* a regular user can initiate.

Tables added:
- `roles` — per-tenant named role (e.g. "standard_user", "savings_only")
- `role_permissions` — per-role, per-transaction-type allow/deny flag
- `user_roles` — many-to-many between users and roles

Endpoints added (`/api/v1/roles`):
- `POST /roles` — create a role (admin only)
- `GET /roles` — list roles in tenant
- `PATCH /roles/{role_id}` — update name / description / status
- `POST /roles/{role_id}/permissions` — set transaction-type permission
- `DELETE /roles/{role_id}/permissions/{transaction_type}` — remove
- `POST /users/{user_id}/roles` — assign role to user
- `DELETE /users/{user_id}/roles/{role_id}` — remove role from user
- `GET /users/{user_id}/roles` — list user's roles

Integration — role check becomes **step 1** of the payment orchestration
sequence (Pay-PRD-0260). Applied to:
- `POST /payments/p2p` (transaction_type = "p2p")
- `POST /redemption/initiate` (transaction_type = "redemption")

Out of scope for F.3:
- Limits + pricing (steps 2 & 3 of orchestration — Phase G)
- Default role auto-assignment policy (handled in seed for local dev)
- Cross-tenant role transfer (PRD non-goal)

## 2. Data flow

```
[User initiates P2P / redemption]
                |
                v
[Payments / Redemption service]
                |
                |  step 1: check user has a role permitting this transaction_type
                v
[Roles service.has_permission(user_id, "p2p")]
   1. SELECT roles FROM user_roles JOIN roles WHERE user_id=? AND roles.status='active'
   2. For each active role: check role_permissions for (transaction_type, permitted=true)
   3. Return True iff ANY role grants permission
                |
                |  false → raise NotAuthorised (403)
                |  true  → continue
                v
[step 2: limits check ... eventually]
[step 3: pricing ... eventually]
[step 4: ledger write — already done in earlier phases]
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption |
|---|---|---|
| Admin → role CRUD endpoints | JSON body + Keycloak JWT | F.1 admin auth + new `platform-admin` requirement |
| Payment service → roles service | function call | In-process; user_id comes from request (test-only) / session (F.4) |
| Roles service → DB | SELECT only on user_roles + role_permissions | Tenant scope enforced via JOINs |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Caller spoofs user_id in P2P body to use another user's role | High (no auth in body still) | High | Carried-over residual from Phase B; F.4 resolves user_id from session token | accepted (Phase F.4 fixes) |
| T-1 | Tampering | Admin assigns themselves a role they shouldn't have | Med | Med | Role CRUD requires `platform-admin` realm role via F.1 dependency | mitigated |
| T-2 | Tampering | Role permissions modified between check and ledger write | Low | Med | Role check happens inside the same DB transaction as the ledger write; permission snapshot is consistent | mitigated |
| R-1 | Repudiation | Admin denies revoking a user's role | Med | Med | F.5 will wire audit_log entries on every role/permission change; for now CRUD is test-only | accepted (Phase F.5 wires audit) |
| I-1 | Info disclosure | Listing roles in tenant A reveals other tenants' roles | Low | Low | `tenant_id` filter on every query | mitigated |
| D-1 | DoS | Tenant with millions of role rows slows the check | Low | Low | Single user_id-indexed join; not a real concern at expected scale | accepted |
| E-1 | Elevation | User with one role obtains permissions from another role | Critical | Critical | `has_permission` returns True only if a role assigned to user_id grants it; no implicit inheritance | mitigated |
| E-2 | Elevation | Inactive role still grants permission | Med | High | `WHERE roles.status='active'` filter; tests verify | mitigated |

## 5. Project-specific test scenarios

Role CRUD:
1. Create role → 201; row in `roles` with status=active
2. Duplicate (tenant_id, name) → 409
3. Set permission `(role, p2p, true)` → 201
4. Update permission `(role, p2p, false)` → row updated, count stays at 1
5. Remove permission → 204; row gone
6. Assign role to user → 201; row in user_roles
7. Cross-tenant assign role to a user in another tenant → 404
8. List user's roles → returns only that user's roles
9. Deactivate role → role lookup still works but permission check returns False

Permission check integration:
10. User with no roles attempts P2P → 403 not_authorised; no ledger write
11. User with role but role lacks p2p permission → 403 not_authorised
12. User with role that has p2p=false explicitly → 403
13. User with role granting p2p → 200; ledger written
14. User with role granting p2p, role then deactivated → next attempt 403
15. User with multiple roles, ANY grants permission → 200
16. Same flow for redemption initiate

Tenant isolation:
17. Role created in tenant A doesn't appear in tenant B's list
18. Permission check is per-tenant via roles.tenant_id

## 6. Residual risks accepted for F.3

- `sender_user_id` in P2P body is still test-only — Phase F.4 will swap to session token. Until then, the role check is verifying permissions against a CLAIMED user_id, not an authenticated one. Documented; doesn't reduce defence in depth for the role check itself.
- No audit log writes on role / permission changes yet. Phase F.5 wires audit-everywhere.
- No "default role" concept in schema — applications/seed assign manually. This is intentional; auto-default-role would be a feature, not a security gap.

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Test scenarios enumerated
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-30
