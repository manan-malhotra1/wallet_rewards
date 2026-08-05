# 04 — Maker-Checker & Approvals

> **Document type:** Low-Level Design (LLD) — the *how*.
> **Purpose:** how governance is built — three parallel maker-checker subsystems that share one
> propose→approve→apply-in-one-transaction shape, and the single `/approvals` admin surface that
> merges them.
> **Related:** code in `backend/app/modules/{config_requests,money_operations,user_operations}/`,
> `admin-ui/app/(authenticated)/approvals/`, `admin-ui/lib/approvals-filter.ts`.
> **PRD:** Module 1 (user governance), Module 6/14 (config governance), Treasury governance (Epic 18);
> the four-eyes / N-eyes control objectives.
> **Read first:** [README (HLD)](README.md) §6,
> [03 — Money Controls](03-money-controls-pricing-limits-roles-step-up.md) (what config is governed).

---

## 1. Why three subsystems, one shape

Every change that moves money or rewrites money-control config is **two-person**: a *maker*
proposes, a distinct *checker* approves, and the change applies **only on approval, inside the same
DB transaction as the approval**. Three domains need this, and rather than one god-table they are
kept as three purpose-built subsystems that share an identical lifecycle and are merged only at the
UI:

| Subsystem | Governs | Checker role | Quorum |
|---|---|---|---|
| `config_requests` | pricing / commission / tax / limit / wallet_limit / step_up config | config-approver | four-eyes (1 distinct approver) |
| `money_operations` | treasury fund_user / withdraw_user / adjust_system_wallet / create_bank_mirror | treasury-approver | **N-eyes** (`required_approvals ≥ 1`) |
| `user_operations` | admin create_user / update_user | user-approver | four-eyes (1 distinct approver) |

Shared shape (all three): **request row + review rows + audit rows**, a status enum, no
self-approval, deterministic apply, and admin display names cached via `admin_profiles`
(`record_audit_for_admin` upserts names so every audit row is human-readable).

---

## 2. The shared lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING: propose (maker)
    PENDING --> CHANGES_REQUESTED: request-changes (checker, comment required)
    PENDING --> APPLIED: approve (checker ≠ maker; quorum met) — apply runs in SAME txn
    PENDING --> WITHDRAWN: withdraw (maker)
    CHANGES_REQUESTED --> PENDING: revise (maker; re-runs propose guards) + resubmit
    CHANGES_REQUESTED --> WITHDRAWN: withdraw (maker)
    APPLIED --> [*]
    WITHDRAWN --> [*]
```

- **Status enum** (`CONFIG_STATUS_*` and the money/user-op equivalents): `PENDING`,
  `CHANGES_REQUESTED`, `APPLIED`, `WITHDRAWN`. Terminal = `APPLIED`, `WITHDRAWN`. There is no
  separate `REJECTED` — a checker who objects uses **request-changes** (comment mandatory) and the
  maker either revises or withdraws.
- **No self-approval:** the approving admin's id must differ from the maker → `SelfApprovalForbidden`
  (409).
- **Apply-on-approval-in-one-transaction:** approval stages `status = APPLIED`, writes the review +
  audit rows, then calls the subsystem's `apply_*` **in the same transaction**. Any collision or
  validation failure at apply time rolls the *whole* approval back — the request never lands in a
  half-applied state.
- **Every action** (propose / approve / request-changes / revise / resubmit / withdraw) writes an
  immutable `audit_log` row.

---

## 3. `config_requests` — pricing/limit/tax/commission/step-up/wallet-limit

Governs all six money-control config types (doc 03). Endpoints under `/api/v1/config-requests`
(admin): `POST` propose, `GET` (+ `/history`, `/{id}`), `POST /{id}/{approve|request-changes|
resubmit|withdraw}`, `PATCH /{id}` revise.

- **`propose_config_change`** — `_validate_payload` checks the payload against the config type's
  schema; asserts tenant/scope. Two guards make proposals safe:
  - **Scope-match on UPDATE** — an UPDATE requires `target_config_id` **and**
    `_assert_update_scope_matches_target`: the payload's scope must equal the live target's scope,
    otherwise an approved UPDATE could silently overwrite a *different* scope.
  - **Open-request conflict** — `_open_request_scope_conflict` enforces **one in-flight change per
    `(tenant, config_type, scope)`**; a second proposal on a scope that already has a PENDING /
    CHANGES_REQUESTED request → `ConfigRequestAlreadyOpen` (409). Snapshots `revision = 1`.
- **`approve_config_request`** — loads the row `FOR UPDATE`; must be `PENDING`; `admin.id != maker`
  else `SelfApprovalForbidden`. Stages `APPLIED` + review + audit, then runs `apply_config_request`
  in the same transaction.
- **`request_config_changes`** — `PENDING → CHANGES_REQUESTED`; comment mandatory
  (`ConfigRequestCommentRequired`, 422).
- **`revise_config_request`** — only the original maker, only from `CHANGES_REQUESTED`; **re-runs the
  same propose guards** (schema + tenant + scope-match-target) and bumps `revision`. A DELETE
  request carries no payload and so is **not revisable**.
- **`resubmit` / `withdraw`** — back to `PENDING` / terminal `WITHDRAWN`.
- **`apply.py::apply_config_request`** — dispatches on the operation:
  - **CREATE** → the type's `create_fn` applies every band (`_DISPATCH`, config_type → schema +
    create fn).
  - **UPDATE** → **atomic replace** (`_REPLACE_DISPATCH`): `replace_fn` deletes the whole scope and
    inserts the new bands in one commit — a config with multiple slab bands is never left partially
    updated.
  - **DELETE** → removes the target's **entire scope** (`_DELETE_SCOPE_DISPATCH`);
    `ConfigRequestTargetNotFound` (404) if the target vanished before apply.
- **History** — `list_config_history_for_scope` + `_synthesize_baseline` reconstruct the applied
  timeline for a scope (drives the compare/restore drawer).

**Exceptions:** `ConfigRequestNotFound` (404), `…InvalidState` (409), `…Forbidden` (403),
`…CommentRequired` (422), `…TargetNotFound` (404), `…AlreadyOpen` (409), `SelfApprovalForbidden` (409).

---

## 4. `money_operations` — treasury movements (N-eyes)

Wraps every treasury money move in an N-eyes approval. Endpoints under `/api/v1/money-operations`
(admin), same verb set as config-requests.

- **`propose_money_operation`** — validates the `operation` payload for one of `fund_user` /
  `withdraw_user` / `adjust_system` / `create_bank_mirror`; `_resolve_required_approvals` sets `N`
  (the column and CHECK support `> 1`, so high-value ops can demand more than two people).
- **`approve_money_operation`** — records the approval; **`distinct_approver_ids`** counts *distinct*
  approvers over the current round. The same admin approving twice → `MoneyOperationDuplicateApprover`
  (409); the maker approving → `SelfApprovalForbidden`. When distinct approvals reach
  `required_approvals`, it stages `APPLIED` and runs `apply_money_operation` in the same transaction.
- **`apply.py::apply_money_operation`** — dispatches to the treasury service fn
  (`fund_user` / `withdraw_from_user` / `adjust_system_wallet` / `create_bank_mirror`) with **the
  maker as the acting admin** (correct audit attribution — the person who initiated the move owns it),
  and a **deterministic idempotency key `money-op-<request-id>`**. That key is the replay-safety
  guarantee: because `post_transaction` is idempotent on `(tenant_id, idempotency_key)` (doc 02),
  a re-approval or retry of the *same* request can never double-post. `applied_transaction_id` is
  captured in a follow-up commit for all ops except `create_bank_mirror`.
- **Resubmit resets the approval round** — after changes are requested and the maker resubmits, a
  previously-approving admin may approve again (the round is fresh).

**Exceptions:** `MoneyOperationNotFound` (404), `…InvalidState` (409), `…Forbidden` (403),
`…DuplicateApprover` (409), `SelfApprovalForbidden` (409).

---

## 5. `user_operations` — admin create/edit user (four-eyes)

Wraps admin `create_user` / `update_user` in four-eyes. Endpoints under `/api/v1/user-operations`
(admin), same verb set.

- **`propose_user_operation`** — validates the payload; for `update_user`, `_assert_target_exists`
  (404). For `create_user`, the **duplicate-identifier guard** `_assert_create_identifiers_available`
  rejects at propose time if any identifier — canonicalised via **`normalize_identifier`, exactly
  matching the apply-time insert** — is either (a) already owned by a live user **or** (b) already
  claimed by another PENDING `create_user` proposal → `IdentifierAlreadyInUse` (409). This stops two
  proposals stacking on the same phone/email. **The same guard re-runs on revise**, so an edit can't
  reintroduce a now-conflicting identifier.
- **`approve_user_operation`** — same distinct-approver + self-approval rules
  (`UserOperationDuplicateApprover`, `SelfApprovalForbidden`); on quorum, `apply_user_operation`
  calls identity `create_user` / `admin_update_user` with the maker as acting admin, in the same
  transaction.

**Exceptions:** `UserOperationNotFound` (404), `…InvalidState` (409), `…Forbidden` (403),
`…DuplicateApprover` (409), `IdentifierAlreadyInUse` (409).

---

## 6. The unified `/approvals` admin surface

The backend keeps three routers; the admin UI merges them into **one screen** with a **role-gated
tab bar** over three queues (`admin-ui/app/(authenticated)/approvals/`):

| Tab | Queue | Visible to |
|---|---|---|
| Configuration | `config_requests` | config-approver (+ platform-admin) |
| Transactions | `money_operations` | treasury-approver (+ platform-admin) |
| Users | `user_operations` | user-approver (+ platform-admin) |

- **Server fetch:** each visible queue is fetched **in full (all statuses)** because the tab counters
  need every row.
- **Client faceting** (`ApprovalsToolbar` over the already-loaded rows, no refetch): free-text search
  (maker / entity / request id), a **status** segmented control with per-status counts, a **type**
  multi-select (options vary per tab), and a **date-range** preset. Facets mirror to the URL and
  render removable chips + "Clear all" + an "X of Y" count.
- **Faceting logic** is a pure module `admin-ui/lib/approvals-filter.ts` — an `ApprovalRow` model
  with `STATUS_KEYS` (PENDING / CHANGES_REQUESTED / APPLIED / WITHDRAWN), `DateRangeKey`
  (7d/30d/90d/all), and `applyFilters` / `countByStatus` / `summarize`. It is unit-tested and carries
  part of the `admin-ui/lib` coverage gate.
- **Per-row verbs** delegate to each domain's existing tables and detail drawers
  (`config-requests/_components/request-detail-drawer.tsx` with `config-detail`/`config-compare`,
  `money-operation-detail-drawer.tsx`, `user-operation-detail-drawer.tsx`). The three old top-level
  routes (`/config-requests`, `/money-operations`, `/user-operations`) are now thin `redirect()`
  stubs into `?tab=…`.
- The **Approvals badge** in the sidebar is computed in the authenticated layout by summing PENDING
  rows across the queues the operator can actually approve. Detail: [doc 09](09-admin-ui.md).

---

## 7. Requirement map

| Control objective | Built as |
|---|---|
| Config changes are four-eyes | `config_requests` propose→approve→apply, scope-match + open-conflict guards |
| Treasury moves are N-eyes | `money_operations`, `distinct_approver_ids` vs `required_approvals` |
| Admin user create/edit is four-eyes | `user_operations`, dup-identifier guard at propose + revise |
| No self-approval | `admin.id != maker` → `SelfApprovalForbidden` (all three) |
| Approval can't double-post | apply-in-one-transaction + deterministic `money-op-<id>` idempotency key |
| Every governed action is auditable | `audit_log` row per verb; names cached via `admin_profiles` |
| One operator inbox | unified `/approvals` (three role-gated queues merged in the UI) |
