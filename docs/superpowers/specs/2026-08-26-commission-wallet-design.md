# Commission Wallets, Parent Commission & Bulk Disbursement — Design

**Date:** 2026-08-26
**Status:** Draft — awaiting review. No code written.
**Supersedes:** Epic B8 in `docs/BACKLOG.md` (raised 2026-08-23). B8's blocker, Story B8.5, is **cleared** — the configurable-user-types edition landed on `main` (`3bb0854`) and the four `user_type` CHECK constraints are gone.
**Scope:** `backend/app/shared/models/{accounts,tenants,commissions,ledger}.py`, new `backend/app/shared/models/commission_batches.py`, new `backend/app/modules/commission_batches/`, plus `backend/app/modules/{commissions,pricing,identity,instruments,tenants,treasury,ledger,limits}`, `admin-ui/app/(authenticated)/{tenants,pricing,users,commission-disbursement,commission-withdrawal}`, and the mobile balance cards. Two Alembic migrations. **Amends ledger invariant #11.**

## 1. Problem

Commission is paid straight into the earner's spendable wallet. `assemble_charges`
builds `DEBIT commission pool → CREDIT financial_wallet`
(`backend/app/modules/cashin/service.py:318` — "commission lands on the agent's
float"), flagged `skip_receive_cap=True` so it lands regardless of the earner's
`max_balance`. The commission is therefore spendable the instant it is earned,
and there is no window in which an operator can review how it was accrued.

Three things follow from that, and this design addresses all three:

1. **No fraud-review window.** An agent who accrues commission through
   fraudulent or erroneous transactions has already spent it by the time
   month-end reconciliation notices.
2. **No hierarchy compensation.** A super-agent earns nothing from the agents
   they supervise. `users.parent_user_id` exists and nothing reads it for
   commission — explicitly deferred at Pricing v2
   (`specs/2026-07-12-pricing-v2-design.md` §Phase 2, D4: "v1 = commission to
   the acting agent only").
3. **No clawback path.** Commission credited in error cannot be pulled back
   other than by a manual single-user treasury withdrawal.

## 2. What exists today (grounding)

| Thing | Where | Note |
|---|---|---|
| `commission_configs` | `backend/app/shared/models/commissions.py` | Per (tenant, txn-type, currency, user_type) + amount band. `fixed_commission`, `variable_commission_pct`, `commission_cap`. No `account_type` dimension |
| `calculate_commission` | `backend/app/modules/commissions/service.py:84` | Returns a bare `Decimal`. Missing config = `Decimal("0")`, deliberately NOT fail-closed (commission is additive, not a mandatory charge) |
| Commission callers | `cashin`, `cashout`, `external` services | Three call sites |
| Charge assembly | `backend/app/modules/pricing/assembler.py` | `ChargeAccounts.agent_account_id` is the commission CREDIT target. `ChargeAccounts.commission_pool_account_id` is the DEBIT side |
| `commission` pool account | `ACCOUNT_TYPE_COMMISSION`, `backend/app/shared/models/accounts.py` | Tenant-level, one per (tenant, currency). Unguarded, may run negative; the operator tops it up |
| Balance guard | `post_transaction`, invariant #11 | Locks `financial_wallet` legs + the `system_cash_inflow` float in canonical account-id order. Two guard shapes exist |
| User hierarchy | `users.parent_user_id` | Nullable self-link. Two-level cap locked as user-types D7. Nothing reads it for commission |
| User-type categories | `user_type_categories` | `consumer`, `retail`, `business`. `retail`/`business` support hierarchy |
| Maker-checker (money) | `backend/app/shared/models/money_operations.py` | Epic 18. N-eyes quorum, `approval_policies`, append-only review thread. Single-operation JSONB payload — no per-row state |
| Instrument backfill | `backend/app/modules/instruments/service.py:242` | `_backfill_user_accounts` gives every existing tenant user an account for a newly created instrument |
| Account provisioning at user create | — | **Does not exist.** `identity.create_user` (`:434-541`) inserts `users`, the default role, identifiers, profile and referral rows, and no `Account`. The partner path (`external/service.py:189`) and self-registration both call the same function. Financial wallets have no lazy get-or-create; `cashin` 404s with `AccountNotFound` (`:92`) when one is missing. Only **points** accounts auto-provision (`rewards/service.py:95`) |
| File upload | — | **Does not exist.** `python-multipart` is installed and unused; no CSV or spreadsheet parsing anywhere |

## 3. Decisions locked

| # | Decision | Rationale |
|---|---|---|
| D1 | New account type `commission_wallet`, per (tenant, user, currency), **distinct from the tenant-level `commission` pool** | The pool is the funding source; the wallet is the earner's holding account. Conflating them would break the double-entry shape |
| D2 | The existing `financial_wallet` **is** the main wallet. No new account type, no second wallet — it is relabelled "Main wallet" in admin UI, mobile and docs | There is exactly one spendable wallet and it already exists. Introducing a parallel type would fork every money path |
| D3 | Tenant flag `commission_wallet_enabled`, chosen **at tenant creation and immutable thereafter** — no later ON, no OFF | Removes every partial-state question: no backfill-on-flip, no teardown of non-zero balances, no third `backfill_pending` state. See §13 R1 for the accepted cost |
| D4 | Eligibility is read from the user-type **category** (Retail, Business). Consumers never get one, and asking for one is refused, not silently created | An operator-created Business type gets a commission wallet with no code change. Hardcoding a type list is the exact coupling the user-types edition removed |
| D5 | Guard shape: **floored at zero, no `max_balance` ceiling, no rolling receive caps.** Amends invariant #11 | "Agents can accrue any amount of commission" — so no ceiling. But a disbursement or withdrawal must never overdraw it — so a floor. This is a third guard shape, not either existing one |
| D6 | Commission destination is a **per-rule choice** on `commission_configs`: `main_wallet` or `commission_wallet` | The operator decides per service and per user type whether commission is immediately spendable or held for review. A global retarget would remove a control the business wants |
| D7 | `payout_destination = 'commission_wallet'` requires the tenant flag ON **and** a non-NULL `user_type` in the Retail or Business category. Validated at config write, 422 | Makes "the dropdown must not even populate" enforceable server-side. Removes the catch-all-band ambiguity (a NULL-type rule could otherwise match a consumer) at configuration time rather than at payout |
| D8 | Parent commission is a **% of the transaction amount** with the **same amount bands and precedence** as the child terms, so both legs ride one config row | Symmetric with the child terms, one band-replace, one resolver, no new join. Parent terms are mandatory in the request but may be zero |
| D9 | Parent resolution walks **exactly one level** via `users.parent_user_id`, never a chain | Consistent with the two-level cap locked as user-types D7 |
| D10 | **Fail-open on the parent leg only.** No parent / ineligible category / no commission wallet / zero rate → the child commission still pays and the skip reason is recorded | A standalone agent with no super-agent is a normal case, not an operator error, and must not block their cash-in |
| D11 | Tax applies to the **parent leg** exactly as to the child leg — same `commission_tax_inclusive` flag, computed per leg independently | A commission is a commission; taxing one and not the other would be arbitrary and would not reconcile |
| D12 | **Main wallet is provisioned at user create for every user** — consumer, retail and business — one per active financial instrument. Commission wallet is provisioned at the same moment for eligible users when the flag is on | Closes a pre-existing gap (§2). A user created after the last instrument currently gets no wallet at all and 404s on their first cash-in |
| D13 | Bulk batches live in a **new `commission_batches` module** reusing Epic 18's `approval_policies`, quorum and review thread | A 5,000-row file needs per-row status, which the single-payload JSONB `money_operations` design cannot hold. Reusing the approval machinery keeps one set of maker-checker semantics |
| D14 | **Disbursement and withdrawal are two separate menus**, not one with a destination selector | They are different business acts with different reason codes: disbursement pays the earner, withdrawal claws money back to the operator |
| D15 | **Partial success.** Invalid rows are skipped with a per-row reason and downloadable; valid rows post | A single bad MSISDN must not block a 5,000-row month-end run |
| D16 | **Checker rejects the whole batch, and REJECTED is terminal.** The maker corrects and uploads a fresh batch | Simplest correct v1. No revise-in-place state machine, no partial-approval semantics |
| D17 | **CSV only** | No new spreadsheet dependency. Excel opens and writes CSV natively |
| D18 | Commission already paid into main wallets **stays there**. No migration | The ledger is append-only. Document it |

## 4. Data model

### 4.1 `accounts` — new account type

```python
ACCOUNT_TYPE_COMMISSION_WALLET = "commission_wallet"
```

Added to `ACCOUNT_TYPES` and the `ck_accounts_type` CHECK. Per (tenant, user,
currency) — the existing `uq_accounts_user_scoped` partial unique index
(`WHERE user_id IS NOT NULL`) already enforces this. **No new index.**

Financial instruments only. A PTS instrument provisions no commission wallet.

### 4.2 `tenants` — new column

| Column | Type | Notes |
|---|---|---|
| `commission_wallet_enabled` | `Boolean NOT NULL` | `server_default 'false'`. Set at tenant creation. Immutable — the update path refuses any change with 422 `commission_flag_immutable` |

### 4.3 `commission_configs` — four new columns

| Column | Type | Notes |
|---|---|---|
| `payout_destination` | `String(20) NOT NULL` | `server_default 'main_wallet'`. CHECK `IN ('main_wallet','commission_wallet')` |
| `parent_fixed_commission` | `NUMERIC(20,6) NOT NULL` | `server_default '0'`. CHECK `>= 0` |
| `parent_variable_commission_pct` | `NUMERIC(8,6) NOT NULL` | `server_default '0'`. CHECK `>= 0 AND < 1` |
| `parent_commission_cap` | `NUMERIC(20,6) NULL` | Open-ended when NULL |

The DB defaults exist **only** so the migration can backfill existing rows. At
the Pydantic layer the three parent fields are **required with no default**, so
an admin must explicitly type a value — zero is a decision, not an omission.

`uq_commission_configs_scope` is unchanged: destination and parent terms are
attributes of a band, not part of its identity.

### 4.4 `transactions` — new column

| Column | Type | Notes |
|---|---|---|
| `parent_commission_amount` | `NUMERIC(20,6) NOT NULL` | `server_default '0'`. Sits alongside the existing `commission_amount` |

The parent skip reason (D10) is recorded on the transaction's existing metadata
payload rather than a dedicated column — it is diagnostic, not a money field.

### 4.5 `commission_batches`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid_pk` | |
| `tenant_id` | `UUID FK tenants.id NOT NULL` | Indexed |
| `batch_type` | `String(20) NOT NULL` | CHECK `IN ('disbursement','withdrawal')` |
| `status` | `String(30) NOT NULL` | CHECK — see lifecycle below |
| `file_name` | `String(255) NOT NULL` | As uploaded, for the audit trail |
| `row_count_total` | `Integer NOT NULL` | Rows parsed from the file |
| `row_count_valid` | `Integer NOT NULL` | Rows that survived pass-1 validation |
| `amount_total` | `NUMERIC(20,6) NOT NULL` | Sum of valid rows' amounts |
| `destination_account_id` | `UUID FK accounts.id NULL` | Withdrawal only — the named `operator_adjustment` bank mirror. NULL for disbursement |
| `created_by_admin_id` | `UUID NOT NULL` | The maker |
| `required_approvals` | `Integer NOT NULL` | Snapshotted at propose time from `approval_policies` |
| `created_at` / `updated_at` | | |

**Lifecycle:** `PENDING → APPROVED → APPLIED | APPLIED_PARTIAL`, or
`PENDING → REJECTED` (terminal), or `PENDING → WITHDRAWN` (maker cancels).
`REJECTED`, `APPLIED`, `APPLIED_PARTIAL` and `WITHDRAWN` are terminal — per D16
a rejected batch is never revised in place.

Approvals reuse Epic 18's shape exactly: a `commission_batch_reviews`
append-only thread (`batch_id`, `admin_id`, `decision`, `comment`,
`created_at`) with a `UniqueConstraint(batch_id, admin_id)` so one checker
cannot supply two of the required approvals. **There is no
`approvals_received` counter column** — the count is derived from DISTINCT
approvers in the thread, matching `money_operations/service.py:367`. A stored
counter would be a second source of truth that can disagree with the thread.
`required_approvals` is CHECK-constrained to `IN (1, 2)` like its Epic 18
counterpart.

### 4.6 `commission_batch_rows`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid_pk` | |
| `batch_id` | `UUID FK commission_batches.id NOT NULL` | Indexed |
| `row_number` | `Integer NOT NULL` | 1-based line in the source file, for the rejects report |
| `msisdn` | `String(30) NOT NULL` | Raw, as uploaded |
| `currency` | `String(10) NOT NULL` | **Mandatory** — a user may hold several commission wallets and the file must say which |
| `amount` | `NUMERIC(20,6) NOT NULL` | |
| `note` | `Text NULL` | **Maker-supplied only.** The system never writes here |
| `resolved_user_id` | `UUID FK users.id NULL` | NULL when the MSISDN did not resolve |
| `resolved_account_id` | `UUID FK accounts.id NULL` | The commission wallet |
| `balance_snapshot` | `NUMERIC(20,6) NULL` | Commission wallet balance at pass-1 validation |
| `snapshot_at` | `TIMESTAMP(tz) NULL` | So the checker can see how stale the snapshot is |
| `status` | `String(20) NOT NULL` | CHECK `IN ('valid','rejected','posted','failed')` |
| `failure_reason` | `String(100) NULL` | Machine code, e.g. `msisdn_not_found`, `insufficient_commission_balance` |
| `transaction_id` | `UUID NULL` | Set on `posted` |

`UniqueConstraint(batch_id, row_number)`.

### 4.7 `approval_policies` — CHECK extension

`ck_approval_policies_operation` is extended with `'commission_disbursement'`
and `'commission_withdrawal'`, so a tenant can require six-eyes on a bulk run
while keeping four-eyes on a single treasury operation.

## 5. Ledger guard — invariant #11 amendment

The choke point today knows two guard shapes. The commission wallet is a third:

| Account | Floor (≥ 0) | Ceiling (`max_balance`) | Rolling caps |
|---|---|---|---|
| `financial_wallet` | yes (overdraft) | yes | yes |
| `system_cash_inflow` | yes (`InsufficientFloat`) | no | no |
| **`commission_wallet`** | **yes** (`InsufficientCommissionBalance`, 409) | **no** | **no** |

`commission_wallet` therefore **joins the locked set** in `post_transaction`:
its account row is locked `FOR UPDATE` in canonical (account-id-sorted) order
alongside the other guarded legs, held through commit, and a net debit that
would drive the balance below zero is rejected.

Consequences and non-consequences, stated explicitly:

- The floor applies to **any** net debit, reversals included. This does not
  conflict with the existing reversal fail-open (corollary (b)), which exempts
  *ceilings*; a credit is never floored, so a reversal that restores funds is
  unaffected.
- No ceiling means `skip_receive_cap` is **redundant** on a commission leg
  targeting a commission wallet. The flag is kept but applied **conditionally**
  — still required when `payout_destination = 'main_wallet'`.
- The commission wallet is **excluded from spendable balance everywhere**:
  money-path available-balance reads, the limits service, admin user detail and
  the mobile balance cards.
- Commission credits **do** produce ledger entries and a `transactions` row, and
  **do** appear in the user's statement. "Do not log the commission wallet row"
  meant exempt it from the caps, not from the ledger — the ledger is the source
  of truth for its balance and invariant #1 is absolute.

`CLAUDE.md` invariant #11 and `.claude/rules/ledger-invariants.md` must be
updated in the same change. A guard shape that exists in code but not in the
rule file is how the M-01 class of bug returns.

## 6. Provisioning

Three trigger points. All idempotent, all tenant-scoped.

**6.1 User create** — `identity.create_user`, covering the admin, partner
(`external`) and self-registration paths, which all funnel through it.

- A `financial_wallet` per **active financial instrument**, for **every** user
  regardless of category (D12). This closes the pre-existing gap in §2.
- A `commission_wallet` per active financial instrument when the tenant flag is
  on **and** the user's type resolves to the Retail or Business category.
- Points accounts are untouched — `rewards` already auto-provisions those.

**6.2 Instrument create** — `instruments/service.py:_backfill_user_accounts`
extends to commission wallets. Creating an INR instrument on a flag-on tenant
gives every existing eligible user an INR commission wallet alongside their INR
main wallet, exactly as the main-wallet backfill works today. A PTS instrument
provisions neither.

**6.3 User type-change into an eligible category** — `identity.update_user`
provisions commission wallets on the transition. Type-change **out** of an
eligible category **keeps** the wallet: the ledger is append-only and the
balance may be non-zero. New accruals stop because the config no longer
resolves; the held balance stays disbursable and withdrawable.

**6.4 Retrofit script** — `scripts/backfill_commission_wallets.py`, a script and
not a migration (B4.8 precedent). Because the tenant flag is immutable (D3),
this is the **only** path by which an existing tenant can adopt commission
wallets. It is a deliberate, operator-run data action, documented as such, not a
product feature.

## 7. Payout path

### 7.1 `calculate_commission` returns a result object

The bare `Decimal` return becomes:

```python
@dataclass(frozen=True)
class CommissionOutcome:
    self_amount: Decimal
    parent_amount: Decimal
    destination: str                  # 'main_wallet' | 'commission_wallet'
    parent_user_id: UUID | None
    parent_skip_reason: str | None    # None when the parent leg pays
```

Three call sites change: `cashin`, `cashout`, `external`.

Both amounts use the formula already in place —
`fixed + min(variable_pct * amount, cap or +Inf)`, quantized to 6dp HALF_UP —
the parent's against its own three columns. Both resolve from the **same
config row**, so the band and precedence logic is untouched.

`parent_skip_reason` is one of `no_parent`, `parent_ineligible_category`,
`parent_wallet_missing`, `parent_zero_rate`. Parent == acting user is impossible
by construction (`ck_user_types_no_self_parent` plus the hierarchy validation at
create); assert it anyway.

Missing config still yields zero, not a 422 — commission remains additive and
optional (§2). D7's validation guarantees that a config which *does* resolve can
always be paid.

### 7.2 Destination resolution

| `payout_destination` | Earner category | Credit target |
|---|---|---|
| `main_wallet` | any | earner's `financial_wallet` |
| `commission_wallet` | Retail / Business | earner's `commission_wallet` |
| `commission_wallet` | Consumer | **unreachable** — D7 forbids the config |

A provisioning gap (destination is `commission_wallet`, earner is eligible, but
no wallet row exists) is a **422 before any ledger write**, never a silent
fallback to the main wallet. That is invariant #12 discipline: an operator
misconfiguration must surface loudly rather than quietly paying spendable
commission that was meant to be held. With §6 provisioning in place this is
unreachable in practice; it is a backstop, and it is tested as one.

### 7.3 Assembler

`ChargeAccounts` gains `parent_account_id: UUID | None`; `ChargeAmounts` gains
`parent_commission` and `parent_commission_tax`. The assembler emits a second
`commission` pool DEBIT → parent CREDIT leg, with the parent's tax split
computed by the same `commission_tax_inclusive` rule as the child's (D11),
per leg independently.

Both legs are funded from the same tenant `commission` pool, which stays
unguarded and may run negative — the operator tops it up. A cash-in with a
parent therefore posts up to **three** commission-related credit legs (child,
parent, and the tax collector) against pool debits, and must balance exactly.

## 8. Bulk disbursement and withdrawal

Two menus over one module (D14). Identical mechanics, different postings and
reason codes.

### 8.1 File format (D17)

CSV, header row required:

```
msisdn,currency,amount,note
27831234567,ZAR,1500.00,"Verified against Nov statement; R120 held pending query"
```

`note` is optional per row, maker-authored, and never system-generated. Its
purpose is to justify a delta between what the wallet holds and what is being
moved.

### 8.2 Pass 1 — validation at upload

Every row is checked before the checker ever sees the batch:

| Check | Failure reason |
|---|---|
| MSISDN resolves to a user in this tenant | `msisdn_not_found` |
| User's type is in the Retail or Business category | `user_not_eligible` |
| Currency is an active financial instrument | `unknown_currency` |
| A commission wallet exists for (user, currency) | `commission_wallet_missing` |
| Amount > 0 and parses as a 6dp decimal | `invalid_amount` |
| Amount ≤ current commission wallet balance | `insufficient_commission_balance` |
| No duplicate (msisdn, currency) within the file | `duplicate_row` |

Failing rows are stored `rejected` with their reason and **excluded from the
batch**; passing rows are stored `valid` with `balance_snapshot` and
`snapshot_at`. The maker downloads a rejects CSV — the original columns plus
`row_number` and `failure_reason` — fixes those rows, and uploads them as a
**new batch** (D15).

A batch with zero valid rows is refused outright rather than created empty.

### 8.3 Checker view

Per row: MSISDN, currency, **commission wallet balance snapshot** with its
as-of timestamp, **amount being moved**, the **delta** between them, and the
maker's note. Plus batch totals and row counts.

The delta is the point of the screen: it makes "this agent accrued R1,620 and we
are only paying R1,500" visible, with the maker's note supplying the reason. The
timestamp is shown because the balance can drift between upload and approval —
the snapshot is a decision aid, not a guarantee, and §8.4 re-checks it.

The checker approves, or rejects the **whole batch** with a mandatory comment
(D16). Rejection is terminal; the maker uploads a corrected file as a new batch.

### 8.4 Pass 2 — apply at quorum

When the count of DISTINCT approvers in the review thread reaches
`required_approvals`, each valid row posts through
`post_transaction`, idempotency-keyed per `(batch_id, row_id)`:

- **Disbursement:** `DEBIT user commission_wallet → CREDIT user financial_wallet`.
  The credit is cap-exempt (an earned payout, same rule as commission today);
  the debit is floored by §5.
- **Withdrawal:** `DEBIT user commission_wallet → CREDIT operator_adjustment`
  (the named bank mirror chosen at batch creation), mirroring the posting shape
  of `treasury.withdraw_from_user`.

Balances are re-validated **under the row lock**. A row that no longer passes —
the balance moved between approval and apply — is marked `failed` with its
reason and the batch lands `APPLIED_PARTIAL`. A second rejects CSV is
downloadable, and those rows go into a fresh batch.

Re-applying an already-`APPLIED` batch is a no-op.

## 9. Single-user withdrawal from a commission wallet

`treasury.resolve_user_financial_wallet` (`:305`) hardcodes
`ACCOUNT_TYPE_FINANCIAL_WALLET`. It gains a wallet-type parameter, and the
`money_operations` `withdraw_user` payload gains `wallet_type`
(`main_wallet` | `commission_wallet`, defaulting to `main_wallet` so existing
payloads are unchanged). The existing Epic 18 maker-checker governs it as
before.

## 10. Read surfaces

- **Admin user detail** (`identity/service.py:908`) enumerates account types
  generically, so the commission wallet appears with no query change. It needs
  explicit "Commission wallet" labelling and exclusion from any spendable total.
- **Mobile** shows accrued commission as a separate, clearly non-spendable
  balance card alongside the main wallet.
- **Statement** includes commission credits (§5).
- **Spendable balance** excludes the commission wallet in the limits service and
  every money-path available-balance read.

## 11. Admin UI

| Screen | Change |
|---|---|
| Tenant create | "Enable commission wallets" toggle. Shown **only at create** — the edit form renders it read-only with a note that it is immutable |
| Commission config dialog | `payout_destination` dropdown, and three parent-commission fields (fixed / variable % / cap). The destination dropdown offers "Commission wallet" **only** when the tenant flag is on and the selected user type is in the Retail or Business category (D7) — otherwise the option is absent, not disabled-with-a-tooltip |
| User detail | Commission wallet balance per currency, labelled and visually separated from the main wallet |
| **Commission Disbursement** (new menu) | Upload CSV → validation summary + rejects download → submit for approval → checker table with balance / amount / delta / note → approve or reject-whole-batch → apply result with a second rejects download |
| **Commission Withdrawal** (new menu) | Same flow, plus a bank-mirror picker for the destination account |

Both new screens follow the existing maker-checker page conventions, and every
commission-config write routes through config maker-checker like every other
money config.

## 12. Migration and seed

**Migration A** (schema): `commission_wallet` added to `ck_accounts_type`;
`tenants.commission_wallet_enabled`; the four `commission_configs` columns with
their CHECKs; `transactions.parent_commission_amount`;
`ck_approval_policies_operation` extended.

**Migration B** (new tables): `commission_batches`, `commission_batch_rows`,
`commission_batch_reviews`.

No data migration. Existing `commission_configs` rows backfill to
`payout_destination = 'main_wallet'` and zero parent terms — that is exactly
today's behaviour, so nothing reprices on deploy (D18).

`scripts/seed.py` gains a flag-on tenant with agents holding commission wallets,
a commission config paying to the commission wallet with a non-zero parent rate,
and a super-agent parent, so the whole path is exercisable locally.

## 13. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **The immutable flag (D3) means existing tenants can never adopt commission wallets through the product.** Accepted deliberately in exchange for eliminating every partial-state failure mode | `scripts/backfill_commission_wallets.py` (§6.4) is the sanctioned operator-run retrofit. Document it in the runbook so it is a known path, not a discovery |
| R2 | Adding `commission_wallet` to the locked set changes lock acquisition at the choke point. Getting the canonical ordering wrong reintroduces the M-01 deadlock/race class | The ordering is account-id-sorted and already implemented; the new type joins the same sort. Tests must include concurrent disbursement + accrual on one wallet |
| R3 | Provisioning main wallets at user create (D12) changes behaviour for **every** tenant, not just flag-on ones | It fixes a latent bug (a user created after the last instrument currently 404s on first cash-in). Idempotent, and the instrument backfill already produces the same rows for existing users |
| R4 | Balance drift between the checker's snapshot and apply | Snapshot timestamp shown in the UI; pass-2 re-validation under the row lock (§8.4); `APPLIED_PARTIAL` plus a rejects download rather than a silent partial |
| R5 | Three commission legs plus tax must balance exactly; an off-by-one in the tax split breaks the ledger | Per-leg independent tax computation (D11), and an assembler test asserting `sum(debits) == sum(credits)` across every inclusive/exclusive × parent/no-parent combination |
| R6 | A large CSV parsed in-request could time out | Row cap enforced at upload with a clear error. Streaming parse, no whole-file buffering |

## 14. Testing

Per `.claude/rules/testing.md`, every backend interface gets automation tests.

**Provisioning:** consumer → main wallet only; agent on a flag-on tenant → main +
commission per financial instrument; agent on a flag-off tenant → main only;
PTS instrument → neither; new instrument backfills existing eligible users;
type-change in provisions, type-change out retains; re-provisioning is a no-op;
tenant isolation.

**Guard (§5):** commission wallet accepts a credit far above `max_balance`;
rolling receive caps do not apply; a debit below zero is rejected 409; a
concurrent accrual and disbursement on one wallet serialise correctly.

**Config (D7):** `commission_wallet` destination with the flag off → 422; with a
NULL `user_type` → 422; with a consumer-category type → 422; with a Retail type
on a flag-on tenant → created. Parent fields absent from the request → 422;
explicitly zero → accepted.

**Payout:** cash-in pays the child to the commission wallet and the agent's
spendable balance is unchanged; `main_wallet` destination behaves exactly as
today; parent leg pays a super-agent; no parent → child pays and the skip reason
is recorded; ineligible parent → same; three-leg ledger balances; tax inclusive
and exclusive on both legs; a missing commission wallet 422s **before** any
ledger write.

**Batches:** mixed-validity file posts valid rows and rejects the rest with
correct reasons; rejects CSV round-trips; zero-valid-row file refused; checker
rejection is terminal; quorum enforced and one admin cannot double-approve;
balance drift between approval and apply yields `APPLIED_PARTIAL`; re-apply is a
no-op; totals reconcile exactly to the ledger; tenant isolation; disbursement
credits the main wallet and withdrawal credits the bank mirror.

## 15. Out of scope

- Migrating commission already paid into main wallets (D18)
- Commission hierarchy beyond one level (D9)
- Per-record checker rejection (D16) — whole-batch only in v1
- Turning the tenant flag off, or on after creation (D3)
- XLSX upload (D17)
- Scheduled or automatic disbursement runs — every run is operator-initiated
- A commission statement/accrual report as a separate artefact; the batch
  screens' drill-down covers the review need for v1
