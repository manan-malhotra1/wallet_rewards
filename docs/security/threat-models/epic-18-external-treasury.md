# Threat Model — Epic 18 External Partner Treasury (Fund / Withdraw)

> **Date:** 2026-07-09
> **Reviewer:** security agent (adversarial VAPT — STRIDE + OWASP API Top 10 2023)
> **PRD reference:** Pay-PRD-0200 (idempotency), Pay-PRD-0220 (overdraft),
> Pay-PRD-0260 (orchestration order) · NFR-0130, NFR-0170, NFR-0210, NFR-0220, NFR-0250, NFR-0260
> **Code reference:** `app/modules/external/{router,service,schemas}.py`,
> `app/modules/treasury/{router,service,schemas}.py`,
> `app/modules/payments/service.py` (top_up + the P2P lock we compare against),
> `app/modules/limits/service.py`, `app/modules/ledger/service.py`,
> `app/auth/{api_key,hmac}.py`
> **Scope commits:** 311308e → 3c9640a (on `main`)
> **Status:** H-01 (ship blocker) FIXED — the original 2026-07-09 fix was INCOMPLETE
> (closed only the warm path; on the cold path a lazy counter-account `commit()`
> released the wallet lock mid-flow), COMPLETED 2026-07-10 (lock moved to the caller +
> counter account pre-created). M-01 max-balance race CLOSED + `amount` bounded
> 2026-07-10 — mandatory partner funding ceiling RESOLVED 2026-07-10 (product decision:
> fail-OPEN accepted, NOT implemented — see §8). M-03
> FIXED 2026-07-09. M-02, M-04, L-01–L-03 remain pre-go-live / hardening items; N-01
> (cold-path counter-create → 500) added 2026-07-10 (LOW, money-safe). See §8.

---

## 1. What this feature does

A third-party partner moves **real money** on an end-user's wallet over the Epic 14
API-key + HMAC surface:

- `POST /api/v1/external/fund` — CREDIT a user's `financial_wallet`
  (reuses `payments.top_up`: DEBIT `system_cash_inflow`, CREDIT user wallet).
- `POST /api/v1/external/withdraw` — DEBIT a user's `financial_wallet`
  (reuses the treasury core `post_user_withdraw`: DEBIT user wallet, CREDIT
  `operator_adjustment`). Supports `withdraw_all: true` → pull the full available
  balance.

Both derive the tenant from the API key (`principal.tenant_id`), never the body.
The user is resolved by identifier (phone/email/account/card), never a UUID. The
partner's required `Idempotency-Key` header **is** the ledger transaction key, so a
network retry returns the original result instead of double-moving money. Type-aware
limits run because a partner is less trusted than an operator. Every call writes a
`record_audit_for_system` row with `actor_id="apikey:<key_id>"`.

Epic 18 S1 also refactored the admin path: `treasury.withdraw_from_user` now shares
`resolve_user_financial_wallet` / `resolve_withdraw_amount` / `post_user_withdraw`
with the partner path, and the admin `POST /api/v1/treasury/withdraw` gained the same
`withdraw_all` flag.

## 2. Data flow

```
[Partner backend]
  │  POST /api/v1/external/{fund,withdraw}
  │  X-Sasai-Api-Key: sak_...          (public handle)
  │  X-Sasai-Signature: t=..,v1=..     (HMAC-SHA256 over {t}.{raw_body}, 300s window)
  │  Idempotency-Key: <required>        ← IS the ledger txn key
  │  body: {identifier_type, identifier_value, amount|withdraw_all, currency, reason?}
  │        extra='forbid' · NO tenant_id · NO user_id · NO status
  ▼
[require_api_key]  auth/api_key.py:94
  │  read raw body → resolve ACTIVE key → Fernet-decrypt secret → verify_signature
  │  → per-key 60/min quota (POST-auth) → principal(tenant_id, key_id)
  ▼
[external_fund / external_withdraw]  external/service.py:56 / :131
  │  tenant_id = principal.tenant_id                              ✓ never from body
  │  resolve_user_financial_wallet(tenant, identifier, currency)  ✓ user_id NOT NULL → never a system wallet
  │  _find_by_idempotency(tenant, key)  ← FAST-PATH before limits/posting
  │        └─ HIT → return existing txn's result (NO re-move)     ✓ retry-safe
  │  ── FUND ──                          │  ── WITHDRAW ──
  │  check_limits('top_up')              │  resolve_withdraw_amount (overdraft check — NO LOCK, H-01)
  │  top_up() → check_wallet_receive     │  check_limits('withdraw') + check_wallet_send
  │      (max_balance — NO LOCK, M-01)   │  post_user_withdraw() → post_transaction
  │  post_transaction (COMMIT)           │      (COMMIT — NO LOCK, H-01)
  │  record_audit_for_system  ← 2nd COMMIT, AFTER the money move (M-04)
  ▼
[FundUserResponse / WithdrawFromUserResponse]  → new_balance disclosed (L-01)
```

## 3. Trust boundaries

| Boundary | What crosses it | Trust assumption | Reality |
|---|---|---|---|
| Partner → `/fund`,`/withdraw` | key_id + HMAC signature + body | Key proves tenant; HMAC proves integrity+origin; body is data only | Holds for tenant scoping + no mass-assignment (`extra='forbid'`, no tenant_id/user_id/status) ✓ |
| Partner → target wallet | identifier | Resolves to a user-owned `financial_wallet` in the key's tenant | Cannot hit a system wallet (user_id filter) ✓, but **any** user_type is reachable, incl. agent/merchant/head_merchant (M-02) |
| Concurrency → balance | two in-flight requests, distinct keys | Overdraft / limits enforced before write | **False** for withdraw: no row lock → TOCTOU race drives the wallet negative (H-01). False for fund's max-balance cap (M-01) |
| Idempotency-Key → txn | partner-chosen string | Same key = same logical op = original result | Scoped only to `(tenant_id, key)`, not to op/body → a reused key across ops returns a mismatched txn (M-03) |
| Stolen/leaked key → money | Fernet-at-rest + HMAC | Only the holder can move money | Holds cryptographically; but a valid key can **mint** balances (fund) unbounded absent opt-in limits (M-01) and one-shot **drain** any wallet (withdraw_all, M-02) |
| Money move → audit | same session, 2nd commit | Every move is audited atomically | Audit commits AFTER the ledger commit → crash window = unaudited move; race = duplicate audit row (M-04) |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation / Status |
|---|---|---|---|---|---|
| S-1 | Spoofing | Forge a fund/withdraw without the secret | Low | High | HMAC-SHA256 + constant-time compare over `{t}.{raw_body}` — **mitigated** (Epic 14) |
| S-2 | Spoofing | Set `tenant_id`/`user_id` via body to move another tenant's money | Low | High | No such fields; `extra='forbid'`; tenant from key; user resolved by identifier — **mitigated** |
| S-3 | Spoofing | Replay a captured signed request within the 300s window | Med | High | Idempotency-Key is inside the signed body → byte-identical replay hits the idempotency guard, no second move — **mitigated** (this is the "tie replay to a real Idempotency-Key" Epic 14 residual, now satisfied) |
| T-1 | Tampering | Mutate body after signing | Low | High | HMAC covers raw body — **mitigated** |
| T-2 | Tampering | **Overdraft a wallet by racing two withdraws (distinct keys) past the balance check** | **High** | **High** | **OPEN — H-01.** No `SELECT … FOR UPDATE`; every other money path locks |
| T-3 | Tampering | Inflate a balance past `max_balance` by racing two funds | Med | Med | **CLOSED — M-01.** Guard holds the wallet `FOR UPDATE` lock across the max-balance read + credit commit (invariant #11). (Cap is opt-in — see §8 mandatory-ceiling decision) |
| T-4 | Tampering | Reused Idempotency-Key across ops returns a mismatched txn / conflicting body not rejected | Med | Med | **OPEN — M-03.** Fast-path keyed only on `(tenant,key)` |
| T-5 | Tampering | Direct UPDATE of ledger money | Low | High | Only append via `post_transaction`; status untouched here — **mitigated** |
| R-1 | Repudiation | A money move leaves no audit trail | Med | Med | **OPEN — M-04.** Audit is a 2nd commit after the ledger commit (crash window); race duplicates it |
| I-1 | Info disclosure | Enumerate which identifiers/wallets exist + their balances in the tenant | Med | Low | **OPEN — L-01.** Distinct 404 codes + `new_balance` in response; rate-limited 60/min |
| I-2 | Info disclosure | Secret / PIN / raw identifier leaks via audit or logs | Low | High | Audit stores `apikey:<key_id>` (public handle), amount, currency, txn_id, `user_id` (UUID) — no secret/PII; no module logging — **mitigated** (nit: partner `reason` free-text, L-02) |
| D-1 | DoS | Unauthenticated flood / huge body before auth; per-key limit is post-auth | Med | Med | Inherited Epic 14 M3 (pre-auth body read, post-auth throttle) — **deferred, tracked in Epic 14** |
| E-1 | Elevation | Partner escapes its tenant (fund/withdraw another tenant's user) | Low | High | tenant from key; `resolve_identifier` + wallet query + `post_transaction` all tenant-scoped — **mitigated** |
| E-2 | Elevation/$$ | Partner moves money on privileged user_types (agent/merchant/head_merchant) or one-shot drains via `withdraw_all` | Med | High | **OPEN — M-02.** No user_type scoping; `withdraw_all` needs no balance knowledge |

## 5. Findings (severity-ranked)

| ID | Sev | Title | File:line | OWASP |
|---|---|---|---|---|
| H-01 | HIGH | Withdraw path has **no wallet row-lock** → concurrent distinct-key withdraws race the overdraft check and drive the wallet **negative** (double-spend); `withdraw_all` amplifies | `treasury/service.py:153-163,166-201`; `external/service.py:149-187`; cf. lock at `payments/service.py:210` | API6 |
| M-01 | MED | Fund is **unbounded balance-minting** for a valid/stolen key: the only cumulative guard (`max_balance`) is opt-in **and** race-able (no lock); `top_up` rolling caps never aggregate (`initiated_by=NULL`); `amount` has no max bound | `external/service.py:86-105`; `limits/service.py:499-506`; `payments/service.py:448-454,477` | API6 / API4 |
| M-02 | MED | Partner can fund/withdraw **any user_type** (agent, merchant, head_merchant, super_agent), not just consumers; `withdraw_all` drains a wallet in one call with no balance knowledge | `treasury/service.py:100-134`; `external/schemas.py:72-96` | API5 / API3 |
| M-03 | MED | Idempotency fast-path keyed only on `(tenant_id, key)` — not op/body: a key reused across fund↔withdraw (or any txn type) silently returns a **mismatched** transaction; conflicting-body reuse does **not** 409 (unlike the ledger layer) | `external/service.py:37-53,75-84,153-162` | API6 / API8 |
| M-04 | MED | Audit row is a **second commit AFTER** the ledger move → a crash in the window leaves an **unaudited** money movement; a concurrent same-key race writes a **duplicate** audit row | `external/service.py:106-120,188-203` | API8 (governance) |
| L-01 | LOW | Identifier/wallet **existence + balance oracle**: `404 user_not_found` vs `404 account_not_found` vs success, plus `new_balance` in the response, let a partner enumerate registered PII and balances in its tenant | `treasury/service.py:118-134`; `external/router.py:113` | API1 / API2 |
| L-02 | LOW | Partner-supplied `reason` free-text is stored unvalidated in the compliance `audit_log.after_state` (log-shaping / PII-stuffing by the partner) | `external/service.py:117,201`; `external/schemas.py:69,87` | API3 |
| L-03 | INFO | `currency` accepts len 2–10 while the ledger is `CHAR(3)`; `amount` has `gt=0` but no `max_digits`/`decimal_places` bound | `external/schemas.py:67-68,84,86` | API4 |

### 5.1 Finding detail

**H-01 — Withdraw double-spend / overdraft race (no row lock). SHIP BLOCKER.**
`external_withdraw` (`external/service.py:149-187`) resolves the wallet, computes the
withdrawable amount in `resolve_withdraw_amount` (`treasury/service.py:137-163`) —
which reads `derive_balance` and does `if available < amount: raise InsufficientFunds`
— then posts the debit via `post_user_withdraw` → `post_transaction`. **No
`SELECT … FOR UPDATE` is taken on the wallet anywhere in this path.** A `grep` for
`with_for_update` shows every other money-moving service locks the balance-bearing
account before the check: P2P (`payments/service.py:210`), redemption
(`redemption/service.py:299`), airtime (`airtime/service.py:229`), budgets, rewards.
Treasury/external is the lone exception.

*Exploit (concrete):* user wallet holds 100 ZAR. Fire two concurrent
`POST /api/v1/external/withdraw` with **distinct** Idempotency-Keys, each
`amount:"100"` (or `withdraw_all:true`):
1. Both requests get separate sessions. Both call `resolve_withdraw_amount` →
   `derive_balance` returns 100 under READ COMMITTED (neither has written yet) →
   both see `available = 100`.
2. `100 < 100` is false for both → both pass the overdraft check.
3. Distinct keys → neither `_find_by_idempotency` (external) nor `post_transaction`'s
   `(tenant_id, idempotency_key)` unique constraint collide → **both commit** a
   DEBIT 100.
4. Final wallet balance = **-100**; `operator_adjustment` is credited 200 — the
   operator has paid out twice what the user held.

This violates ledger-invariants §6 (no negative available balance) and Pay-PRD-0220.
The per-key 60/min limit does not stop two concurrent requests. `withdraw_all` makes
it worse: an attacker needn't know the balance, and two racing `withdraw_all` calls
each pull the full amount. The same gap exists on the admin `withdraw_from_user`
(pre-existing), but Epic 18 newly exposes it to an internet-facing, less-trusted
partner **and** adds `withdraw_all`.
*Fix:* lock the wallet before reading the balance and hold it through the debit
commit — reuse the existing pattern: `SELECT Account.id WHERE id=wallet.id FOR UPDATE`
at the top of `external_withdraw` (and `withdraw_from_user`), or push the lock into
`post_user_withdraw` before `resolve_withdraw_amount`'s read. This also serialises the
rolling-limit aggregation for same-wallet withdraws (see M-01's second axis).

**M-01 — Fund is unbounded balance-minting; the one cumulative guard is opt-in and
race-able.** `external_fund` (`external/service.py:56-128`) calls
`check_limits('top_up')` then `top_up`, whose only cumulative guard is
`check_wallet_receive_limits` (`payments/service.py:448-454`). Blast radius of a
valid/stolen key:
1. *No mandatory ceiling.* Both `check_limits` and `check_wallet_receive_limits`
   are **no-ops when no config row exists** (`limits/service.py:214-215,490-491`). A
   tenant that has not configured a `top_up` `LimitConfig` **and** a
   `WalletLimitConfig.max_balance` for the currency has **no cap at all** — the key
   can mint arbitrary balances onto any user.
2. *Rolling top_up caps are structurally dead.* `top_up` posts `initiated_by=None`
   (`payments/service.py:477`), and `_aggregate_user_txns` counts only
   `initiated_by == user_id` (`limits/service.py:154`). So even a configured
   daily/weekly/monthly `top_up` cap never sees partner funds — only the per-txn
   `max_amount` bites. (The code comment at `external/service.py:86-88` acknowledges
   this; the point here is that it leaves `max_balance` as the *sole* cumulative
   guard.)
3. *`max_balance` is race-able.* `check_wallet_receive_limits` reads
   `derive_balance` then the credit lands later with no lock
   (`limits/service.py:499-506`) — same TOCTOU class as H-01: concurrent funds each
   see the pre-credit balance and both pass.
4. *No amount bound.* `amount` is only `gt=0` (`external/schemas.py:67`); a single
   fund can be an arbitrarily large/precise Decimal.
*Fix:* require a per-tenant partner funding ceiling (mandatory `LimitConfig` or a
dedicated partner cap; fail-closed rather than pass-through for this untrusted
surface), lock the wallet in the receive check, and bound `amount`
(`max_digits`/`decimal_places`).

*Decision (2026-07-10, product owner):* the race + `amount` axes are done (see §8);
the **mandatory-ceiling** axis is resolved **fail-OPEN** — funding is NOT gated on a
configured cap on either the partner (`external_fund`) or operator (`fund_user`)
surface. Unconfigured tenants can therefore still be funded without a cumulative
bound (accepted residual risk, NOT a mitigation); operators MUST set a `max_balance`
before enabling a partner key as the compensating control (once set, invariant #11
enforces it authoritatively under the wallet lock). See §8.

**M-02 — No user_type scoping; `withdraw_all` one-shot drain.**
`resolve_user_financial_wallet` (`treasury/service.py:100-134`) resolves **any** user
with a `financial_wallet` — consumer, agent, super_agent, merchant, head_merchant.
A partner key can therefore `withdraw_all` from a head_merchant's or super_agent's
wallet (typically large balances), or fund/withdraw any of them. `withdraw_all`
(`external/schemas.py:85`) needs no knowledge of the balance to empty a wallet.
Combined with a stolen key this is a materially larger blast radius than a
consumer-only partner surface. *Fix:* confirm business intent; if partners are meant
to touch only end-users, restrict the resolved `user_type` to `consumer` (mirror the
Epic 14 create-user path that forces `user_type="consumer"`), and consider dropping
`withdraw_all` from the partner surface (keep it admin-only) or gating it.

**M-03 — Idempotency key not scoped to the operation/body.**
`external/service.py:_find_by_idempotency` (37-53) matches purely on
`(tenant_id, idempotency_key)`. It does not check `transaction_type`, the resolved
user, the amount, or the currency. Consequences:
- A partner that reuses key `K` on `/withdraw` after using it on `/fund` gets the
  **fund** transaction back, shaped as a `WithdrawFromUserResponse` (with the *new*
  `user_id` but the *old* txn's `amount`/`transaction_id`) and **no withdraw
  happens** — a silent no-op that can desync the partner's ledger.
- Reusing `K` with a **different body** returns the original **without a 409**,
  whereas the ledger layer (`ledger/service.py:161-169`) would raise
  `DuplicateIdempotencyKey`. The fast-path masks the conflict the platform otherwise
  surfaces (weakens Pay-PRD-0200's "different body → conflict" contract).
No direct double-move results (the fast-path returns before posting), so this is
correctness/robustness, not money-loss. *Fix:* scope the fast-path lookup to the
endpoint's `transaction_type` (and ideally assert the resolved user + amount/currency
match, else 409), so a reused key can only ever replay the *same* logical op.

**M-04 — Audit committed after the money move.** In both functions the sequence is
`post_user_withdraw`/`top_up` → `post_transaction` (which **commits** the ledger
move internally) → `record_audit_for_system` (adds the row) →
`session.commit()` (`external/service.py:106-120,188-203`). The audit is therefore a
**separate, later** commit. A crash between the ledger commit and the audit commit
leaves a committed money movement with **no audit row** — contra NFR-0250 for a
state-changing partner action. Additionally, on the concurrent same-key race both
callers reach `record_audit` (the loser gets the winner's txn back from
`post_transaction`), producing a **duplicate** audit row for one move, and for
`withdraw_all` the loser's audited `amount` is its own independently-computed value,
which can differ from what actually moved. This is the same two-commit pattern as the
admin treasury path and Epic 17's initiate; noting it here because the partner surface
raises the compliance stakes. *Fix:* fold the audit into the same commit as the money
move (requires `post_transaction` to not self-commit, or an audit-after-reconcile
sweep), and skip the audit when `post_transaction` returned an existing row.

**L-01 — Existence + balance oracle.** Unknown identifier → `UserNotFound`
(`404 user_not_found`); known user without a wallet in that currency →
`AccountNotFound` (`404 account_not_found`); success → `201` with `new_balance`. A
partner can therefore (a) enumerate which phones/emails are registered in its tenant,
(b) learn whether they hold a wallet in a given currency, and (c) read the exact
balance of any user it can name. Rate-limited at 60/min and scoped to the partner's
own tenant, so LOW — but it is PII (phone/email) + financial-state disclosure beyond
what crediting/debiting strictly requires. *Fix (optional hardening):* collapse the
two 404s to one code on this surface; consider whether `new_balance` needs to be
returned at all.

**L-02 — Partner-controlled `reason` in the audit.** `reason` (`external/schemas.py:69,87`)
is free text up to 500 chars written straight into `audit_log.after_state`
(`external/service.py:117,201`). A partner can shape misleading audit narratives or
stuff PII into the compliance record. Low risk; note for `compliance`.

**L-03 — Schema/storage drift (informational).** `currency` allows len 2–10 while the
ledger column is `CHAR(3)` (a bogus value just 404s at wallet resolution, so no
security impact); `amount` lacks a `max_digits`/`decimal_places` bound. Mirrors the
same nit in Epic 14/17 schemas. Tighten for defence-in-depth (see M-01 for the amount
bound).

### 5.2 What is correct by design (verified, not findings)

- **Cross-tenant money movement is not possible.** Tenant comes from the key
  everywhere; `resolve_identifier`, the wallet query, and `post_transaction`'s
  `_assert_accounts_belong_to_tenant` are all tenant-scoped. A tenant-A key cannot
  fund/withdraw a tenant-B user or wallet.
- **A system wallet can never be the target.** `resolve_user_financial_wallet` filters
  `Account.user_id == <resolved user_id>` and `account_type='financial_wallet'`;
  system accounts have `user_id IS NULL`, so fund/withdraw/withdraw_all can only ever
  hit a user-owned wallet (`treasury/service.py:122-131`).
- **Mass-assignment / BOPLA is closed.** Both request schemas set
  `extra='forbid'`, carry no `tenant_id`/`user_id`/`status`, and the user is resolved
  by identifier — a partner cannot assert tenant, target user by UUID, or set the
  transaction status/type.
- **Same-key retry does not double-move — even concurrently.** The external fast-path
  is an optimization; the real guard is the `(tenant_id, idempotency_key)` unique
  constraint inside `post_transaction`, whose `IntegrityError`→re-fetch
  (`ledger/service.py:161-169`) makes the losing racer return the winner's single
  transaction. (The *money* is safe on same-key races; the *audit* is not — M-04.)
- **HMAC replay is neutralised for these non-idempotent ops** by the enforced
  Idempotency-Key living inside the signed body (S-3) — the property Epic 14's
  threat model flagged as missing for future non-idempotent endpoints.
- **`withdraw_all` is correctly bounded sequentially** — full available balance,
  `NothingToWithdraw` (409) on an empty wallet, and it is still subject to
  `check_limits('withdraw')` per-txn max + `check_wallet_send_limits`. Its only
  unsafe edge is the H-01 race.
- **No secret / PIN / raw identifier in the audit or logs.** Audit actor is the
  public `key_id`; entity is the `user_id` UUID; no module-level logging.

## 6. Residual risks (accepted / to confirm)

- **Global-admin key minting (inherited, Epic 14).** One platform-admin token mints a
  partner key for any tenant; a stolen admin token compromises every tenant's partner
  money surface. Accepted for Phase 1.
- **Pre-auth work + post-auth throttle (inherited, Epic 14 M3).** `require_api_key`
  reads the raw body and does a DB lookup + Fernet decrypt before the per-key quota is
  charged. Tracked in the Epic 14 model; unchanged here.
- **Two-commit audit pattern is repo-wide.** M-04 is the partner-surface instance of a
  pattern shared with admin treasury, airtime initiate, and P2P. A structural fix
  (audit inside the money commit) should be scoped repo-wide, not just here.
- **Stolen-key blast radius is the dominant risk for this epic.** Even with H-01 and
  M-01 fixed, a leaked key can move real money within its tenant up to the configured
  ceilings. Operators MUST configure fund/withdraw limits before enabling a partner
  key, and key rotation/leak response (Epic 14) is the compensating control.

## 7. Required regression tests (hand to `automation-testing`)

- `test_external_withdraw_concurrent_distinct_keys_cannot_overdraft` — two concurrent
  withdraws (distinct keys) totalling > balance on a wallet leave balance ≥ 0 and post
  exactly one debit (H-01). Include a `withdraw_all` × 2 variant.
- `test_external_fund_concurrent_cannot_exceed_max_balance` — two concurrent funds
  (distinct keys) cannot push the wallet past a configured `max_balance` (M-01).
- ~~`test_external_fund_without_limits_is_capped`~~ — DROPPED 2026-07-10: the
  mandatory-ceiling axis of M-01 was resolved fail-OPEN (§8), so there is no
  "capped without a configured limit" behaviour to assert. Enforcement *when a cap
  IS configured* is covered by `test_external_fund_concurrent_cannot_exceed_max_balance`.
- `test_external_withdraw_rejects_non_consumer_user` (or asserts the allowed set) —
  a partner cannot withdraw/fund an agent/merchant/head_merchant if scoping is added
  (M-02).
- `test_external_idempotency_key_is_operation_scoped` — a key used on `/fund` then
  reused on `/withdraw` does NOT return the fund txn; a conflicting-body reuse returns
  409, not a silent original (M-03).
- `test_external_money_move_writes_exactly_one_audit_row` — one audit row per move,
  none duplicated on a same-key race, with `actor_id="apikey:<key_id>"`, amount,
  currency, txn_id and no secret/PII (M-04).
- `test_external_fund_withdraw_cross_tenant_isolation` — a tenant-A key cannot resolve
  or move money on a tenant-B user/wallet (E-1 regression guard).
- `test_external_withdraw_never_targets_system_wallet` — an identifier can never
  resolve a `user_id IS NULL` account (design guard).
- `test_external_auth_and_existence_errors_are_minimally_distinguishable` — decide and
  lock the 404 policy (L-01).
- `test_ledger_sum_to_zero` after every external fund/withdraw test (existing
  invariant harness) — confirms no path breaks double-entry even under the race.

## 8. Sign-off

- [x] STRIDE pass complete
- [x] OWASP API Top 10 (2023) pass complete
- [x] Fintech-specific scenarios exercised against code: cross-tenant money movement,
  double-move on retry (incl. concurrent same-key + concurrent distinct-key),
  withdraw-all bounds + system-wallet reachability, fund = minting blast radius,
  limit bypass via fast-path ordering, mass-assignment/BOPLA, user enumeration,
  HMAC replay, audit completeness, operator-vs-partner privilege
- [x] Cross-tenant isolation, system-wallet unreachability, no-mass-assignment,
  same-key retry safety, and HMAC-replay neutralisation **verified correct**
- [x] **H-01 (withdraw overdraft race) — original 2026-07-09 fix was INCOMPLETE;
  COMPLETED 2026-07-10.** The 2026-07-09 fix locked the wallet INSIDE
  `resolve_withdraw_amount`, which closed only the WARM path. On the COLD path (first
  withdraw per (tenant, currency)) the lazy `_get_or_create_operator_adjustment`
  `commit()` ran mid-flow — inside `post_user_withdraw`, AFTER the lock — and RELEASED
  the `FOR UPDATE` lock before the debit was posted, so two concurrent distinct-key
  withdraws still both passed the overdraft check and drove the balance negative
  (reproduced from a clean DB: `[201, 201]`, final balance −100). Completed fix: the lock
  moved to the callers (`external_withdraw:189`, `withdraw_from_user:451`) and the counter
  account is pre-created via `get_or_create_operator_adjustment` BEFORE the lock, so the
  lock now spans acquisition → `post_transaction`'s debit commit with NO intervening
  commit (verified read-only under the lock: `resolve_withdraw_amount`, `check_limits`,
  `check_wallet_send_limits`, `resolve_user_type`). Covers external + admin paths;
  mirrors payments/redemption/airtime. Regression (REAL concurrent-race tests, stable
  6/6 — each asserts one 201 + one 409, wallet never negative, exactly one debit, and
  ledger nets to zero under the race): `test_external_withdraw_concurrent_distinct_keys_cannot_overdraft`,
  `test_external_withdraw_all_concurrent_cannot_double_drain`.
- [x] **M-03 — FIXED 2026-07-09**: the external idempotency fast-path rejects a key
  reused for a different operation (`transaction_type` mismatch → 409).
- [x] **M-01 (max-balance race + amount bound) — FIXED 2026-07-10.** The fund path now
  holds the wallet lock across `check_wallet_receive_limits`' balance read (inside
  `top_up`) and the credit commit — `system_cash_inflow` is pre-created before the lock
  so its lazy create can't release the lock mid-flow (same shape as H-01). Two concurrent
  funds can no longer both read the pre-credit balance and race past `max_balance`.
  `amount` bounded to the ledger's `Numeric(20, 6)` (`max_digits`/`decimal_places`).
  Regression: `test_external_fund_concurrent_cannot_exceed_max_balance` (one 201 + one
  409 `max_balance_exceeded`, balance stays at the cap, ledger nets to zero).
- [x] **M-01 (mandatory funding ceiling) — RESOLVED 2026-07-10: fail-OPEN accepted (NOT
  implemented).** Product-owner decision: do NOT gate funding on a configured ceiling, on
  either the partner (`external_fund`) or operator (`fund_user`) surface. The `amount` bound
  caps a single request's precision, NOT cumulative partner funding; `max_balance` / `top_up`
  limits stay OPT-IN and the rolling `top_up` caps are structurally dead (`initiated_by=NULL`).
  **Consequence (accepted risk, NOT a mitigation):** a valid/stolen key — or an operator — on
  a tenant with no configured ceiling can still mint unbounded balances. Rationale: the
  operator path is Keycloak-admin + fully audited, and gating the partner path would block
  legitimate funding (e.g. new-tenant onboarding) until a limit exists, pushing operators
  toward bogus-high caps. Compensating controls (unchanged, see §6): operators MUST configure
  a `max_balance` before enabling a partner fund key — once set, invariant #11 enforces it
  authoritatively under the wallet lock (`test_external_fund_concurrent_cannot_exceed_max_balance`)
  — with Epic 14 key rotation/leak response as the secondary control. Revisit if KYC/AML
  transaction monitoring (Phase 2) lands.
- [ ] M-02 (consumer-only scoping) — confirm whether a partner may fund/withdraw
  non-consumer (agent / merchant / head_merchant) wallets before go-live.
- [ ] M-04 (audit-after-commit window) — repo-wide pattern; address platform-wide.
- [ ] L-01 / L-02 / L-03 — hardening follow-up.
- [ ] **N-01 (cold-path counter-account create → HTTP 500) — hardening, LOW, money-safe.**
  Surfaced by the completed H-01 fix moving counter-account creation ahead of the wallet
  lock: two concurrent FIRST-EVER fund/withdraws for a new (tenant, currency) can both
  find the counter account missing and both `INSERT`; the `uq_accounts_system_scoped`
  partial unique index (`accounts.py:114-121`) makes the loser's `commit()` raise
  `IntegrityError`, which neither `get_or_create_operator_adjustment`
  (`treasury/service.py:89-97`) nor `get_or_create_system_cash_inflow`
  (`payments/service.py:397-405`) catches, and `main.py` registers no `IntegrityError`
  handler → HTTP 500. NO overdraft/double-spend — it occurs BEFORE the wallet lock and
  any ledger write — and it is self-healing (warm path never recurs). Newly reachable for
  withdraw (pre-fix the wallet lock serialised withdraws before the create); pre-existing
  for fund (never had a lock). Not observed in the harness (its scheduler runs one task
  far enough ahead that the loser goes warm → clean 409). Fix: catch `IntegrityError` and
  re-SELECT the winner's row — mirror `post_transaction` (`ledger/service.py:161-169`) /
  `create_account` (`accounts/service.py:78-88`).
- Reviewed by: security agent (adversarial) 2026-07-09 (H-01 + M-03 fixed by lead
  2026-07-09); re-verified adversarially 2026-07-10 — H-01 original fix found INCOMPLETE
  (cold-path lock-release via mid-flow commit) and now COMPLETED; M-01 max-balance race
  CLOSED + `amount` bounded (mandatory ceiling RESOLVED fail-OPEN 2026-07-10 by
  product owner — see §8); real concurrent-race
  regressions added; new finding N-01 (LOW).
