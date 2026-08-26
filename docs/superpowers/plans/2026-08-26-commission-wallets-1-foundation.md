# Commission Wallets — Plan 1 of 3: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every user a main wallet at creation, give Retail/Business users a `commission_wallet` alongside it on flag-on tenants, and guard that wallet correctly at the ledger choke point.

**Architecture:** A new `commission_wallet` account type joins the ledger's overdraft-guarded set but is deliberately excluded from the `max_balance` ceiling — which requires splitting one implicit guard rule into two explicit ones. Account provisioning moves into a single idempotent helper called from all three trigger points (user create, instrument create, type change), replacing the current situation where nothing provisions financial wallets at user creation at all.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, pytest / pytest-asyncio, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-08-26-commission-wallet-design.md` — §4.1, §4.2, §5, §6, §10. Decisions D1–D5, D12.

**Branch:** `feature/commission-wallets` (already created; the spec commit is on it).

---

## Prerequisites

Read before starting:
- `docs/superpowers/specs/2026-08-26-commission-wallet-design.md` §5 and §6
- `.claude/rules/ledger-invariants.md` — the M-01 bug class this plan touches
- `CLAUDE.md` invariant #11 and invariant #3 (no DDL outside Alembic)

Environment:
```bash
cd sasai-wallet-infra && docker compose up -d
cd ../backend && source .venv/bin/activate
alembic upgrade head
```

The current Alembic head is `0065` (`20260824_0065_drop_requires_merchant_profile.py`). This plan adds `0066`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/shared/models/accounts.py` | **Modify** — add `ACCOUNT_TYPE_COMMISSION_WALLET` constant and extend `ck_accounts_type` |
| `backend/app/shared/models/tenants.py` | **Modify** — add `commission_wallet_enabled` column |
| `backend/app/shared/exceptions/__init__.py` | **Modify** — add `InsufficientCommissionBalance` |
| `backend/app/modules/ledger/service.py` | **Modify** — split the guard into overdraft-set and ceiling-set; add the new type to the former only |
| `backend/app/modules/accounts/provisioning.py` | **Create** — the single idempotent "which wallets should this user hold" helper. One responsibility, called from three places |
| `backend/app/modules/user_types/service.py` | **Modify** — add `is_commission_wallet_eligible` category check |
| `backend/app/modules/identity/service.py` | **Modify** — call provisioning from `create_user` and on type change in `update_user` |
| `backend/app/modules/instruments/service.py` | **Modify** — extend `_backfill_user_accounts` to commission wallets |
| `backend/app/modules/tenants/service.py` | **Modify** — accept the flag at create, refuse it on update |
| `backend/alembic/versions/20260826_0066_commission_wallet_foundation.py` | **Create** — account type CHECK + tenant flag |
| `backend/scripts/backfill_commission_wallets.py` | **Create** — operator-run retrofit (spec §6.4) |
| `CLAUDE.md`, `.claude/rules/ledger-invariants.md` | **Modify** — invariant #11 amendment |

Provisioning lives in its own file rather than inside `accounts/service.py` because it is orchestration across three domains (instruments, user types, accounts) and will be called from identity and instruments — putting it in `service.py` would create import cycles with `user_types`.

---

## Task 1: Account type constant and tenant flag

**Files:**
- Modify: `backend/app/shared/models/accounts.py`
- Modify: `backend/app/shared/models/tenants.py`
- Create: `backend/alembic/versions/20260826_0066_commission_wallet_foundation.py`
- Test: `backend/tests/accounts/test_commission_wallet_type.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/accounts/test_commission_wallet_type.py`:

```python
"""The commission_wallet account type exists and is persistable.

Guards the CHECK constraint extension in migration 0066: a commission_wallet
row must insert cleanly, and the type must be distinct from the tenant-level
`commission` pool it is often confused with (spec D1).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPES,
    Account,
    Tenant,
    User,
)


def test_commission_wallet_is_a_distinct_account_type() -> None:
    assert ACCOUNT_TYPE_COMMISSION_WALLET == "commission_wallet"
    assert ACCOUNT_TYPE_COMMISSION_WALLET in ACCOUNT_TYPES
    assert ACCOUNT_TYPE_COMMISSION_WALLET != ACCOUNT_TYPE_COMMISSION


@pytest.mark.asyncio
async def test_commission_wallet_row_persists(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    account = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_COMMISSION_WALLET,
        currency="ZAR",
    )
    db_session.add(account)
    await db_session.commit()

    found = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalar_one()
    assert found.currency == "ZAR"


@pytest.mark.asyncio
async def test_tenant_commission_flag_defaults_false(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    await db_session.refresh(test_tenant)
    assert test_tenant.commission_wallet_enabled is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/accounts/test_commission_wallet_type.py -v
```

Expected: FAIL — `ImportError: cannot import name 'ACCOUNT_TYPE_COMMISSION_WALLET'`.

- [ ] **Step 3: Add the account type constant**

In `backend/app/shared/models/accounts.py`, after the `ACCOUNT_TYPE_COMMISSION` block, add:

```python
# Commission wallets (spec 2026-08-26, D1). Per (tenant, user, currency), held
# by Retail and Business users only. DISTINCT from ACCOUNT_TYPE_COMMISSION,
# which is the tenant-level pool that FUNDS commission payouts: the pool is the
# source, this wallet is the earner's holding account. Floored at zero but
# uncapped and exempt from rolling receive caps (invariant #11, third shape) —
# an agent may accrue any amount, but a disbursement may never overdraw it.
ACCOUNT_TYPE_COMMISSION_WALLET = "commission_wallet"
```

Add `ACCOUNT_TYPE_COMMISSION_WALLET,` to the `ACCOUNT_TYPES` tuple, and add
`"'commission_wallet', "` to the `ck_accounts_type` CHECK string in
`__table_args__`.

Export it from `backend/app/shared/models/__init__.py` alongside the other
`ACCOUNT_TYPE_*` names.

- [ ] **Step 4: Add the tenant flag column**

In `backend/app/shared/models/tenants.py`, inside `class Tenant`, after
`require_config_to_transact`:

```python
    # Commission wallets on/off for this tenant (spec 2026-08-26, D3).
    # Chosen at tenant CREATION and IMMUTABLE thereafter — `update_tenant`
    # refuses any change with 422 `commission_flag_immutable`. Immutability is
    # deliberate: it removes backfill-on-flip, teardown of non-zero balances,
    # and any `backfill_pending` intermediate state. The only retrofit path for
    # an existing tenant is `scripts/backfill_commission_wallets.py` (spec §6.4).
    commission_wallet_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
```

- [ ] **Step 5: Generate and write the migration**

Create `backend/alembic/versions/20260826_0066_commission_wallet_foundation.py`:

```python
"""Commission wallet foundation — account type + tenant flag.

Adds `commission_wallet` to ck_accounts_type and `tenants.commission_wallet_enabled`.
Spec: docs/superpowers/specs/2026-08-26-commission-wallet-design.md §4.1, §4.2.

Revision ID: 0066
Revises: 0065
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = (
    "'financial_wallet', 'points_account', 'system_points_issuance', "
    "'provider_redemption_wallet', 'system_cash_inflow', 'system_fee_collected', "
    "'operator_adjustment', 'airtime_merchant_holding', 'commission', "
    "'tax_service_collected', 'tax_commission_collected', "
    "'points_redemption_wallet', 'cashback_provider_wallet'"
)
_NEW_TYPES = _OLD_TYPES + ", 'commission_wallet'"


def upgrade() -> None:
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type", "accounts", f"account_type IN ({_NEW_TYPES})"
    )
    op.add_column(
        "tenants",
        sa.Column(
            "commission_wallet_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "commission_wallet_enabled")
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type", "accounts", f"account_type IN ({_OLD_TYPES})"
    )
```

- [ ] **Step 6: Apply the migration and verify model/DB agreement**

```bash
alembic upgrade head && python scripts/check_migrations.py
```

Expected: `check_migrations.py` reports no drift (invariant #3).

- [ ] **Step 7: Run the test to verify it passes**

```bash
pytest tests/accounts/test_commission_wallet_type.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/shared/models/accounts.py backend/app/shared/models/tenants.py \
  backend/app/shared/models/__init__.py \
  backend/alembic/versions/20260826_0066_commission_wallet_foundation.py \
  backend/tests/accounts/test_commission_wallet_type.py
git commit -m "feat(accounts): add commission_wallet account type and tenant flag"
```

---

## Task 2: `InsufficientCommissionBalance` exception

**Files:**
- Modify: `backend/app/shared/exceptions/__init__.py`
- Test: `backend/tests/shared/test_commission_exceptions.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/shared/test_commission_exceptions.py`:

```python
"""InsufficientCommissionBalance shape.

A distinct 409 so an operator can tell "this agent has not accrued that much"
apart from "this user's spendable wallet is short" (InsufficientFunds).
"""

from __future__ import annotations

from app.shared.exceptions import AppHTTPException, InsufficientCommissionBalance


def test_insufficient_commission_balance_shape() -> None:
    exc = InsufficientCommissionBalance()
    assert isinstance(exc, AppHTTPException)
    assert exc.status_code == 409
    assert exc.error_code == "insufficient_commission_balance"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/shared/test_commission_exceptions.py -v
```

Expected: FAIL — `ImportError: cannot import name 'InsufficientCommissionBalance'`.

- [ ] **Step 3: Add the exception**

In `backend/app/shared/exceptions/__init__.py`, next to `InsufficientCashbackFunds`:

```python
class InsufficientCommissionBalance(AppHTTPException):
    """A commission wallet cannot cover this debit (spec 2026-08-26, D5).

    Raised at the ledger choke point when a disbursement, withdrawal or
    clawback would drive a commission wallet below zero. Distinct from
    InsufficientFunds so an operator reviewing a failed batch row can tell
    "this agent never accrued that much" from "this user's spendable wallet
    is short".
    """

    def __init__(self) -> None:
        super().__init__(
            409,
            "insufficient_commission_balance",
            "The commission wallet does not hold enough to cover this amount.",
        )
```

If `exc.error_code` is not the attribute name used by `AppHTTPException` in this
codebase, read the base class at the top of the same file and match its actual
attribute name in both the test and this docstring.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/shared/test_commission_exceptions.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/shared/exceptions/__init__.py backend/tests/shared/test_commission_exceptions.py
git commit -m "feat(exceptions): add InsufficientCommissionBalance"
```

---

## Task 3: Split the ledger guard into two explicit axes

**This is the highest-risk task in the plan. Read spec §5 and `.claude/rules/ledger-invariants.md` before starting.**

The ceiling branch currently keys off `account.user_id is not None`
(`backend/app/modules/ledger/service.py:442`). That works today only because
every guarded type other than `financial_wallet` is a system account with a NULL
`user_id`. A commission wallet **is** user-owned, so adding it to the guarded set
without this split would silently apply `max_balance` to it — the exact opposite
of D5.

**Files:**
- Modify: `backend/app/modules/ledger/service.py:52-68` (the frozenset + comment) and `:425-458` (the guard loop)
- Test: `backend/tests/ledger/test_commission_wallet_guard.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/ledger/test_commission_wallet_guard.py`:

```python
"""Commission wallet guard shape — floored, uncapped, cap-exempt (spec §5, D5).

Three properties, each of which would be silently wrong under a naive
"just add it to the guarded set" change:

  1. A credit far above the owner's max_balance SUCCEEDS (no ceiling).
  2. A debit that would overdraw it is REJECTED with the distinct 409.
  3. A debit it can cover succeeds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import InsufficientCommissionBalance
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    Tenant,
    User,
)


async def _make_account(
    session: AsyncSession, tenant: Tenant, account_type: str, user: User | None
) -> Account:
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id if user is not None else None,
        account_type=account_type,
        currency="ZAR",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _accrue(
    session: AsyncSession,
    tenant: Tenant,
    pool: Account,
    wallet: Account,
    amount: Decimal,
    key: str,
) -> None:
    """Post pool -> commission wallet, the shape a real commission credit uses."""
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=key,
            transaction_type="commission_accrual",
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(pool.id, ENTRY_DEBIT, amount),
                LedgerEntryRequest(wallet.id, ENTRY_CREDIT, amount),
            ],
        ),
    )


@pytest.mark.asyncio
async def test_credit_above_max_balance_succeeds(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """No ceiling: an agent may accrue any amount of commission (D5)."""
    pool = await _make_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _make_account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )

    # Far above any plausible configured max_balance, and NOT flagged
    # skip_receive_cap — the exemption must come from the account TYPE.
    await _accrue(db_session, test_tenant, pool, wallet, Decimal("99999999"), "acc-1")

    from app.modules.accounts.service import derive_balance

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("99999999")


@pytest.mark.asyncio
async def test_debit_below_zero_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Floored: a disbursement may never overdraw a commission wallet (D5)."""
    pool = await _make_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _make_account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _accrue(db_session, test_tenant, pool, wallet, Decimal("100"), "acc-2")

    with pytest.raises(InsufficientCommissionBalance):
        await post_transaction(
            db_session,
            PostTransactionRequest(
                tenant_id=test_tenant.id,
                idempotency_key="disb-over",
                transaction_type="commission_disbursement",
                currency="ZAR",
                amount=Decimal("150"),
                entries=[
                    LedgerEntryRequest(wallet.id, ENTRY_DEBIT, Decimal("150")),
                    LedgerEntryRequest(pool.id, ENTRY_CREDIT, Decimal("150")),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_debit_within_balance_succeeds(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    pool = await _make_account(db_session, test_tenant, ACCOUNT_TYPE_COMMISSION, None)
    wallet = await _make_account(
        db_session, test_tenant, ACCOUNT_TYPE_COMMISSION_WALLET, test_user
    )
    await _accrue(db_session, test_tenant, pool, wallet, Decimal("100"), "acc-3")

    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=test_tenant.id,
            idempotency_key="disb-ok",
            transaction_type="commission_disbursement",
            currency="ZAR",
            amount=Decimal("100"),
            entries=[
                LedgerEntryRequest(wallet.id, ENTRY_DEBIT, Decimal("100")),
                LedgerEntryRequest(pool.id, ENTRY_CREDIT, Decimal("100")),
            ],
        ),
    )

    from app.modules.accounts.service import derive_balance

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/ledger/test_commission_wallet_guard.py -v
```

Expected: `test_debit_below_zero_is_rejected` FAILS — the debit is allowed
through, because `commission_wallet` is not in the guarded set yet, so no floor
applies. The other two may pass for the wrong reason; that is fine, Step 4 makes
them pass for the right one.

- [ ] **Step 3: Split the guard sets**

In `backend/app/modules/ledger/service.py`, replace the
`_OVERDRAFT_GUARDED_ACCOUNT_TYPES` block (currently at `:52-68`) with:

```python
# --- Guard axis 1: the overdraft FLOOR -------------------------------------
# Account types whose net DEBIT is gated by a non-negative floor under the
# FOR UPDATE lock (invariant #11). `financial_wallet` is the spendable user
# wallet; `system_cash_inflow` is the operator cash float, which must be
# pre-funded from the bank; `cashback_provider_wallet` funds internal
# redemption; `commission_wallet` holds accrued agent commission and may never
# be overdrawn by a disbursement, withdrawal or clawback. Each raises a
# DISTINCT error so the operator learns which account to replenish.
_OVERDRAFT_GUARDED_ACCOUNT_TYPES = frozenset(
    {
        ACCOUNT_TYPE_FINANCIAL_WALLET,
        ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        ACCOUNT_TYPE_CASHBACK_PROVIDER,
        ACCOUNT_TYPE_COMMISSION_WALLET,
    }
)

# --- Guard axis 2: the max_balance CEILING ---------------------------------
# Account types whose net CREDIT is gated by the owner's max_balance.
#
# This set is deliberately EXPLICIT rather than derived from
# `account.user_id is not None`. That derivation was correct only while
# `financial_wallet` was the sole user-owned guarded type. `commission_wallet`
# is user-owned AND uncapped (spec D5: an agent may accrue any amount of
# commission), so ownership no longer implies a ceiling. Deriving the ceiling
# from ownership here would silently cap commission accrual — a bug that no
# commission test would catch, because it only fires once an agent's accrual
# crosses their configured max_balance in production.
_CEILING_GUARDED_ACCOUNT_TYPES = frozenset({ACCOUNT_TYPE_FINANCIAL_WALLET})
```

Add `ACCOUNT_TYPE_COMMISSION_WALLET` to the `from app.shared.models import (...)`
block at the top of the file.

- [ ] **Step 4: Apply both axes in the guard loop**

In the same file, in the guard loop (currently `:428-458`), change the floor
branch to add the new error, and the ceiling branch to test the new set.

Floor branch — add one clause before the `raise InsufficientFunds()` fallback:

```python
            if balance - reserved + delta < 0:
                if account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW:
                    raise InsufficientFloat()
                if account.account_type == ACCOUNT_TYPE_CASHBACK_PROVIDER:
                    raise InsufficientCashbackFunds()
                if account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET:
                    raise InsufficientCommissionBalance()
                raise InsufficientFunds()
```

Ceiling branch — replace the `elif` condition and its comment:

```python
        elif (
            not request.is_reversal
            and not request.skip_receive_cap
            and account.account_type in _CEILING_GUARDED_ACCOUNT_TYPES
            and account.user_id is not None
        ):
            # Ceiling applies to the spendable main wallet only. The account_type
            # test is what excludes commission wallets; the user_id test is kept
            # because a capped type always has an owner and it narrows for mypy.
            cap = await resolve_max_balance(
```

Import `InsufficientCommissionBalance` in the exceptions import block at the top.

- [ ] **Step 5: Run the new test to verify it passes**

```bash
pytest tests/ledger/test_commission_wallet_guard.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the full ledger and invariants suites for regressions**

```bash
pytest tests/ledger tests/invariants tests/limits tests/cashin tests/cashout tests/payments -v
```

Expected: all pass. These cover the guard's existing behaviour — a regression
here means the ceiling split changed main-wallet semantics, which it must not.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/ledger/service.py backend/tests/ledger/test_commission_wallet_guard.py
git commit -m "feat(ledger): floor commission wallets without capping them

Splits the implicit ownership-derived ceiling rule into an explicit
_CEILING_GUARDED_ACCOUNT_TYPES set. Commission wallets are user-owned but
uncapped, so 'has a user_id' no longer implies 'has a max_balance'."
```

---

## Task 4: Record the invariant #11 amendment

A guard shape that lives in code but not in the rules file is how the M-01 bug
class returns. This task is not optional and belongs in the same PR.

**Files:**
- Modify: `CLAUDE.md` (invariant #11)
- Modify: `.claude/rules/ledger-invariants.md`

- [ ] **Step 1: Amend the CLAUDE.md invariant**

In `CLAUDE.md`, invariant #11, after the sentence describing which accounts are
skipped by the guard, insert:

```markdown
As of the commission-wallet edition there are **three** guard shapes, and the
ceiling is no longer derivable from account ownership:

| Account type | Floor (≥ 0) | Ceiling (`max_balance`) | Rolling caps |
|---|---|---|---|
| `financial_wallet` | yes (`InsufficientFunds`) | yes | yes |
| `system_cash_inflow` | yes (`InsufficientFloat`) | no | no |
| `cashback_provider_wallet` | yes (`InsufficientCashbackFunds`) | no | no |
| `commission_wallet` | yes (`InsufficientCommissionBalance`) | **no** | **no** |

`commission_wallet` is **user-owned but uncapped**: an agent may accrue any
amount of commission, but no disbursement, withdrawal or clawback may overdraw
it. Because it is the first user-owned type without a ceiling, the ceiling test
is now an explicit `_CEILING_GUARDED_ACCOUNT_TYPES` membership check rather than
`account.user_id is not None`. Any new user-owned account type MUST declare its
membership in both sets deliberately.
```

- [ ] **Step 2: Mirror it into the rules file**

Add the same table and the "explicit membership, never derived from ownership"
paragraph to `.claude/rules/ledger-invariants.md`, next to its existing M-01
discussion.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .claude/rules/ledger-invariants.md
git commit -m "docs(invariants): record the third ledger guard shape"
```

---

## Task 5: Tenant flag at create, immutable on update

**Files:**
- Modify: `backend/app/modules/tenants/service.py`
- Modify: `backend/app/modules/tenants/schemas.py`
- Modify: `backend/app/shared/exceptions/__init__.py`
- Test: `backend/tests/tenants/test_commission_flag.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/tenants/test_commission_flag.py`:

```python
"""The commission wallet flag is creation-time only (spec D3).

Immutability is the decision that removes backfill-on-flip, teardown of
non-zero balances, and any intermediate `backfill_pending` state. It must be
enforced at the service, not merely hidden in the UI.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.schemas import TenantCreateRequest, TenantUpdateRequest
from app.modules.tenants.service import create_tenant, update_tenant
from app.shared.exceptions import CommissionFlagImmutable


@pytest.mark.asyncio
async def test_flag_set_at_creation(db_session: AsyncSession) -> None:
    tenant = await create_tenant(
        db_session,
        TenantCreateRequest(
            name="Commission Co",
            business_type="wallet",
            base_currency="ZAR",
            commission_wallet_enabled=True,
        ),
    )
    assert tenant.commission_wallet_enabled is True


@pytest.mark.asyncio
async def test_flag_defaults_off(db_session: AsyncSession) -> None:
    tenant = await create_tenant(
        db_session,
        TenantCreateRequest(
            name="Plain Co", business_type="wallet", base_currency="ZAR"
        ),
    )
    assert tenant.commission_wallet_enabled is False


@pytest.mark.asyncio
async def test_flag_cannot_be_turned_on_later(db_session: AsyncSession) -> None:
    tenant = await create_tenant(
        db_session,
        TenantCreateRequest(
            name="Later Co", business_type="wallet", base_currency="ZAR"
        ),
    )
    with pytest.raises(CommissionFlagImmutable):
        await update_tenant(
            db_session, tenant.id, TenantUpdateRequest(commission_wallet_enabled=True)
        )


@pytest.mark.asyncio
async def test_flag_cannot_be_turned_off_later(db_session: AsyncSession) -> None:
    tenant = await create_tenant(
        db_session,
        TenantCreateRequest(
            name="OnCo",
            business_type="wallet",
            base_currency="ZAR",
            commission_wallet_enabled=True,
        ),
    )
    with pytest.raises(CommissionFlagImmutable):
        await update_tenant(
            db_session, tenant.id, TenantUpdateRequest(commission_wallet_enabled=False)
        )


@pytest.mark.asyncio
async def test_update_without_the_field_is_unaffected(db_session: AsyncSession) -> None:
    """Restating other fields must not trip the immutability guard."""
    tenant = await create_tenant(
        db_session,
        TenantCreateRequest(
            name="Rename Co",
            business_type="wallet",
            base_currency="ZAR",
            commission_wallet_enabled=True,
        ),
    )
    updated = await update_tenant(
        db_session, tenant.id, TenantUpdateRequest(name="Renamed Co")
    )
    assert updated.name == "Renamed Co"
    assert updated.commission_wallet_enabled is True
```

The exact `create_tenant` / `update_tenant` signatures (whether they take an
`admin` principal, `ip_address`, etc.) must be read from
`backend/app/modules/tenants/service.py` first and matched — pass whatever the
existing tenant tests in `backend/tests/tenants/` pass.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/tenants/test_commission_flag.py -v
```

Expected: FAIL — `ImportError: cannot import name 'CommissionFlagImmutable'`.

- [ ] **Step 3: Add the exception**

In `backend/app/shared/exceptions/__init__.py`:

```python
class CommissionFlagImmutable(AppHTTPException):
    """`tenants.commission_wallet_enabled` was changed after creation (D3).

    The flag is creation-time only. Turning it on later would require a
    backfill with an observable half-provisioned window; turning it off would
    strand non-zero commission balances. The sanctioned retrofit for an
    existing tenant is `scripts/backfill_commission_wallets.py`.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "commission_flag_immutable",
            "Commission wallets can only be enabled when the tenant is created.",
        )
```

- [ ] **Step 4: Accept the flag at create, refuse it at update**

In `backend/app/modules/tenants/schemas.py`, add to `TenantCreateRequest`:

```python
    # Creation-time only (spec D3). Absent = off.
    commission_wallet_enabled: bool = False
```

and to `TenantUpdateRequest`:

```python
    # Present ONLY so an attempt to change it is refused explicitly rather than
    # silently ignored. `update_tenant` raises CommissionFlagImmutable on any
    # non-None value that differs from the stored one.
    commission_wallet_enabled: bool | None = None
```

In `backend/app/modules/tenants/service.py`, set the column in `create_tenant`
from the request, and add this to `update_tenant` **before** any write:

```python
    if (
        payload.commission_wallet_enabled is not None
        and payload.commission_wallet_enabled != tenant.commission_wallet_enabled
    ):
        raise CommissionFlagImmutable()
```

Comparing against the stored value rather than rejecting any non-None keeps
idempotent PUTs that restate the current value working.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/tenants/test_commission_flag.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Run the tenant suite for regressions**

```bash
pytest tests/tenants -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/tenants/ backend/app/shared/exceptions/__init__.py \
  backend/tests/tenants/test_commission_flag.py
git commit -m "feat(tenants): creation-time-only commission wallet flag"
```

---

## Task 6: Category eligibility helper

**Files:**
- Modify: `backend/app/modules/user_types/service.py`
- Test: `backend/tests/user_types/test_commission_eligibility.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/user_types/test_commission_eligibility.py`:

```python
"""Commission wallet eligibility is a CATEGORY question (spec D4).

Never a hardcoded type list: an operator-created Business type must become
eligible with no code change. Retired types stay eligible, because an agent
onboarded under a since-retired type must keep accruing.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import Tenant


@pytest.mark.parametrize(
    ("code", "expected"),
    [("agent", True), ("super_agent", True), ("merchant", True), ("subscriber", False)],
)
@pytest.mark.asyncio
async def test_eligibility_by_seeded_type(
    db_session: AsyncSession, test_tenant: Tenant, code: str, expected: bool
) -> None:
    assert await is_commission_wallet_eligible(db_session, test_tenant.id, code) is expected


@pytest.mark.asyncio
async def test_unknown_type_is_not_eligible(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Never raise on an unresolvable type — provisioning must not 500."""
    assert await is_commission_wallet_eligible(db_session, test_tenant.id, "nope") is False
```

Before running, confirm the seeded type codes and their categories in
`backend/tests/conftest.py:_seed_user_type_catalog` and adjust the parametrize
list to the codes it actually seeds — the assertion is about *categories*
(retail/business eligible, consumer not), not about these specific strings.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/user_types/test_commission_eligibility.py -v
```

Expected: FAIL — `ImportError: cannot import name 'is_commission_wallet_eligible'`.

- [ ] **Step 3: Implement the helper**

In `backend/app/modules/user_types/service.py`:

```python
async def is_commission_wallet_eligible(
    session: AsyncSession, tenant_id: UUID, code: str
) -> bool:
    """Does a user of this type hold a commission wallet? (spec D4)

    Eligibility is a CATEGORY question: Retail and Business hold commission
    wallets, Consumers never do. Reading the category rather than a type list
    is what lets an operator-created Business type work with no code change.

    A RETIRED type is still eligible — an agent onboarded under a type the
    operator has since retired must keep accruing, exactly as `get_user_type`
    keeps existing users working (user-types spec §11).

    Returns False (never raises) for a type that does not resolve, so the
    provisioning path degrades to "no commission wallet" instead of 500ing.
    """
    row = await get_user_type(session, tenant_id, code)
    return row is not None and row.category_code in (CATEGORY_RETAIL, CATEGORY_BUSINESS)
```

Import `CATEGORY_RETAIL` and `CATEGORY_BUSINESS` from
`app.shared.models.user_types` at the top of the file if not already present.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/user_types/test_commission_eligibility.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/user_types/service.py \
  backend/tests/user_types/test_commission_eligibility.py
git commit -m "feat(user-types): add commission wallet eligibility by category"
```

---

## Task 7: The provisioning helper

One function, one responsibility: given a user, make sure they hold exactly the
accounts they should. Idempotent, so all three callers can invoke it freely.

**Files:**
- Create: `backend/app/modules/accounts/provisioning.py`
- Test: `backend/tests/accounts/test_provisioning.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/accounts/test_provisioning.py`:

```python
"""provision_user_accounts — the single source of "which wallets should this user hold".

Called from user create, instrument create and type change (spec §6). Every
caller relies on it being idempotent, so re-running must never duplicate a row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.provisioning import provision_user_accounts
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    Instrument,
    Tenant,
    User,
)


async def _types_held(session: AsyncSession, user: User) -> set[tuple[str, str]]:
    rows = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalars().all()
    return {(a.account_type, a.currency) for a in rows}


async def _add_instrument(
    session: AsyncSession, tenant: Tenant, code: str, account_type: str
) -> Instrument:
    inst = Instrument(
        tenant_id=tenant.id,
        code=code,
        symbol=code,
        display_name=code,
        account_type=account_type,
    )
    session.add(inst)
    await session.commit()
    return inst


@pytest.mark.asyncio
async def test_consumer_gets_main_wallet_only(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Every user gets a main wallet, consumers included (D12)."""
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "subscriber"
    await db_session.commit()
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(db_session, tenant_id=test_tenant.id, user_id=test_user.id)
    await db_session.commit()

    assert await _types_held(db_session, test_user) == {
        (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR")
    }


@pytest.mark.asyncio
async def test_agent_on_flag_on_tenant_gets_both(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    await db_session.commit()
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(db_session, tenant_id=test_tenant.id, user_id=test_user.id)
    await db_session.commit()

    assert await _types_held(db_session, test_user) == {
        (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR"),
        (ACCOUNT_TYPE_COMMISSION_WALLET, "ZAR"),
    }


@pytest.mark.asyncio
async def test_agent_on_flag_off_tenant_gets_main_only(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    test_tenant.commission_wallet_enabled = False
    test_user.user_type = "agent"
    await db_session.commit()
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(db_session, tenant_id=test_tenant.id, user_id=test_user.id)
    await db_session.commit()

    assert await _types_held(db_session, test_user) == {
        (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR")
    }


@pytest.mark.asyncio
async def test_points_instrument_provisions_no_commission_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Financial currencies only — a PTS instrument yields no commission wallet."""
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    await db_session.commit()
    await _add_instrument(db_session, test_tenant, "PTS", ACCOUNT_TYPE_POINTS)

    await provision_user_accounts(db_session, tenant_id=test_tenant.id, user_id=test_user.id)
    await db_session.commit()

    held = await _types_held(db_session, test_user)
    assert (ACCOUNT_TYPE_COMMISSION_WALLET, "PTS") not in held


@pytest.mark.asyncio
async def test_multi_currency(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    await db_session.commit()
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)
    await _add_instrument(db_session, test_tenant, "INR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(db_session, tenant_id=test_tenant.id, user_id=test_user.id)
    await db_session.commit()

    assert await _types_held(db_session, test_user) == {
        (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR"),
        (ACCOUNT_TYPE_COMMISSION_WALLET, "ZAR"),
        (ACCOUNT_TYPE_FINANCIAL_WALLET, "INR"),
        (ACCOUNT_TYPE_COMMISSION_WALLET, "INR"),
    }


@pytest.mark.asyncio
async def test_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """All three callers re-invoke this freely; a second run must add nothing."""
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    await db_session.commit()
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    first = await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()
    second = await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    assert first == 2
    assert second == 0
    assert len(await _types_held(db_session, test_user)) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/accounts/test_provisioning.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.accounts.provisioning'`.

- [ ] **Step 3: Implement the helper**

Create `backend/app/modules/accounts/provisioning.py`:

```python
"""Per-user account provisioning — the single "which wallets should this user hold" rule.

Called from three places (spec §6): `identity.create_user`,
`instruments.create_instrument`'s backfill, and the type-change branch of
`identity.update_user`. Keeping the rule in one function is what stops those
three drifting apart.

Lives in its own module rather than in `accounts/service.py` because it
orchestrates across instruments and user types; importing those from
`service.py` would create an import cycle.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    INSTRUMENT_STATUS_ACTIVE,
    Account,
    Instrument,
    Tenant,
    User,
)


async def provision_user_accounts(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> int:
    """Create every account this user should hold but does not yet.

    One `financial_wallet` (the MAIN wallet) per active financial instrument,
    for EVERY user regardless of category — this closes the pre-existing gap
    where a user created after the last instrument held no wallet at all and
    404'd on their first cash-in (spec §2, D12).

    Plus one `commission_wallet` per active financial instrument when the
    tenant flag is on AND the user's type is in the Retail or Business
    category (D4). Points instruments provision neither: `rewards` already
    auto-provisions points accounts, and there is no commission wallet for a
    points unit.

    Idempotent by construction — existing (user, type, currency) tuples are
    skipped — so every caller may invoke it unconditionally.

    Args:
        session: Async DB session. Rows are ADDED but NOT committed; the caller
            commits, so provisioning joins the caller's transaction and a failed
            user create leaves no orphaned accounts.
        tenant_id: Tenant scope.
        user_id: The user to provision for.

    Returns:
        Number of new Account rows added.
    """
    user = (
        await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        return 0

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        return 0

    currencies = list(
        (
            await session.execute(
                select(Instrument.code).where(
                    Instrument.tenant_id == tenant_id,
                    Instrument.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
                    Instrument.status == INSTRUMENT_STATUS_ACTIVE,
                    Instrument.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    if not currencies:
        return 0

    wants_commission = tenant.commission_wallet_enabled and await is_commission_wallet_eligible(
        session, tenant_id, user.user_type
    )

    held = {
        (row.account_type, row.currency)
        for row in (
            await session.execute(
                select(Account).where(
                    Account.tenant_id == tenant_id, Account.user_id == user_id
                )
            )
        ).scalars().all()
    }

    wanted_types = [ACCOUNT_TYPE_FINANCIAL_WALLET]
    if wants_commission:
        wanted_types.append(ACCOUNT_TYPE_COMMISSION_WALLET)

    added = 0
    for currency in currencies:
        for account_type in wanted_types:
            if (account_type, currency) in held:
                continue
            session.add(
                Account(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_type=account_type,
                    currency=currency,
                )
            )
            added += 1
    if added:
        await session.flush()
    return added
```

Confirm `INSTRUMENT_STATUS_ACTIVE` is exported from `app.shared.models`; if it
is only in `app.shared.models.instruments`, import it from there instead.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/accounts/test_provisioning.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/accounts/provisioning.py backend/tests/accounts/test_provisioning.py
git commit -m "feat(accounts): add idempotent per-user account provisioning"
```

---

## Task 8: Provision at user create

**Files:**
- Modify: `backend/app/modules/identity/service.py` (in `create_user`, before the final `await session.commit()`)
- Test: `backend/tests/identity/test_create_user_provisioning.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/identity/test_create_user_provisioning.py`:

```python
"""Users get their wallets at creation (spec D12).

Before this change NO creation path provisioned a financial wallet: a user
created after the last instrument existed held no account at all and 404'd
with AccountNotFound on their first cash-in. This test locks that shut.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import UserCreateRequest, UserIdentifierIn
from app.modules.identity.service import create_user
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Instrument,
    Tenant,
)


async def _add_zar(session: AsyncSession, tenant: Tenant) -> None:
    session.add(
        Instrument(
            tenant_id=tenant.id,
            code="ZAR",
            symbol="R",
            display_name="Rand",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        )
    )
    await session.commit()


async def _types_held(session: AsyncSession, user_id) -> set[str]:
    rows = (
        await session.execute(select(Account).where(Account.user_id == user_id))
    ).scalars().all()
    return {a.account_type for a in rows}


@pytest.mark.asyncio
async def test_consumer_gets_a_main_wallet(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role
) -> None:
    await _add_zar(db_session, test_tenant)
    user = await create_user(
        db_session,
        UserCreateRequest(
            tenant_id=test_tenant.id,
            user_type="subscriber",
            identifiers=[UserIdentifierIn(identifier_type="phone", identifier_value="+27821110001")],
        ),
    )
    assert await _types_held(db_session, user.id) == {ACCOUNT_TYPE_FINANCIAL_WALLET}


@pytest.mark.asyncio
async def test_agent_on_flag_on_tenant_gets_both(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role
) -> None:
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _add_zar(db_session, test_tenant)

    user = await create_user(
        db_session,
        UserCreateRequest(
            tenant_id=test_tenant.id,
            user_type="agent",
            identifiers=[UserIdentifierIn(identifier_type="phone", identifier_value="+27821110002")],
        ),
    )
    assert await _types_held(db_session, user.id) == {
        ACCOUNT_TYPE_FINANCIAL_WALLET,
        ACCOUNT_TYPE_COMMISSION_WALLET,
    }
```

Match `UserCreateRequest` / `UserIdentifierIn` field names against
`backend/app/modules/identity/schemas.py` and the existing tests in
`backend/tests/identity/` before running — the role fixture name in particular
must match what those tests use.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/identity/test_create_user_provisioning.py -v
```

Expected: FAIL — both assertions get `set()`, because nothing provisions.

- [ ] **Step 3: Wire provisioning into `create_user`**

In `backend/app/modules/identity/service.py`, in `create_user`, immediately
before the `if admin is not None:` audit block and the final commit:

```python
    # Provision the user's wallets INSIDE this transaction (spec D12), so a
    # failed create never leaves orphaned accounts. Every user gets a main
    # wallet; eligible users on a flag-on tenant also get commission wallets.
    # Local import: `provisioning` imports user_types, which imports identity
    # schemas — a module-level import here would cycle.
    from app.modules.accounts.provisioning import provision_user_accounts

    await provision_user_accounts(
        session, tenant_id=request.tenant_id, user_id=user.id
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/identity/test_create_user_provisioning.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run identity, external and cashin suites for regressions**

```bash
pytest tests/identity tests/external tests/cashin -v
```

Expected: all pass. `external` matters because the partner path calls the same
`create_user`; `cashin` matters because tests that previously built wallets by
hand must not now collide with auto-provisioned ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/identity/service.py \
  backend/tests/identity/test_create_user_provisioning.py
git commit -m "feat(identity): provision wallets at user creation"
```

---

## Task 9: Extend the instrument backfill

**Files:**
- Modify: `backend/app/modules/instruments/service.py:242` (`_backfill_user_accounts`)
- Test: `backend/tests/instruments/test_commission_wallet_backfill.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/instruments/test_commission_wallet_backfill.py`:

```python
"""Adding a currency later backfills commission wallets for existing users (spec §6.2).

The business case verbatim: "if an instrument is later added, for example INR,
the older agents and the older retail and business users will also get a
commission wallet, just as we give the new currency wallet to all users."
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


async def _held(session: AsyncSession, user: User, currency: str) -> set[str]:
    rows = (
        await session.execute(
            select(Account).where(Account.user_id == user.id, Account.currency == currency)
        )
    ).scalars().all()
    return {a.account_type for a in rows}


@pytest.mark.asyncio
async def test_new_currency_backfills_both_wallets_for_an_agent(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, admin_principal
) -> None:
    from app.modules.instruments.schemas import InstrumentCreateRequest
    from app.modules.instruments.service import create_instrument

    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    await db_session.commit()

    await create_instrument(
        db_session,
        test_tenant.id,
        InstrumentCreateRequest(
            code="INR",
            symbol="₹",
            display_name="Rupee",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        ),
        admin=admin_principal,
    )

    assert await _held(db_session, test_user, "INR") == {
        ACCOUNT_TYPE_FINANCIAL_WALLET,
        ACCOUNT_TYPE_COMMISSION_WALLET,
    }


@pytest.mark.asyncio
async def test_new_currency_gives_a_consumer_only_the_main_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, admin_principal
) -> None:
    from app.modules.instruments.schemas import InstrumentCreateRequest
    from app.modules.instruments.service import create_instrument

    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "subscriber"
    await db_session.commit()

    await create_instrument(
        db_session,
        test_tenant.id,
        InstrumentCreateRequest(
            code="INR",
            symbol="₹",
            display_name="Rupee",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        ),
        admin=admin_principal,
    )

    assert await _held(db_session, test_user, "INR") == {ACCOUNT_TYPE_FINANCIAL_WALLET}
```

Match the `create_instrument` signature and the admin-principal fixture name
against `backend/tests/instruments/test_instruments_router.py`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/instruments/test_commission_wallet_backfill.py -v
```

Expected: the first test FAILS — only `financial_wallet` is backfilled.

- [ ] **Step 3: Extend the backfill**

In `backend/app/modules/instruments/service.py`, replace the body of
`_backfill_user_accounts` with a version that adds the commission wallet for
eligible users. Keep the existing single-query "users who lack this account"
shape for the main wallet, and add a second pass:

```python
async def _backfill_user_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    account_type: str,
    currency: str,
) -> int:
    """Create one account per tenant user that doesn't yet have one for this instrument.

    Two passes for a financial instrument (spec §6.2): the instrument's own
    account_type for EVERY user, then a `commission_wallet` for users whose
    type is in an eligible category, when the tenant flag is on. A points
    instrument runs the first pass only — there is no commission wallet for a
    points unit.

    Idempotent: pre-existing (user, account_type, currency) tuples are skipped.

    Returns:
        Number of new Account rows inserted across both passes.
    """
    added = await _backfill_one_type(session, tenant_id, account_type, currency)

    if account_type != ACCOUNT_TYPE_FINANCIAL_WALLET:
        return added

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None or not tenant.commission_wallet_enabled:
        return added

    added += await _backfill_one_type(
        session,
        tenant_id,
        ACCOUNT_TYPE_COMMISSION_WALLET,
        currency,
        eligible_only=True,
    )
    return added


async def _backfill_one_type(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    account_type: str,
    currency: str,
    *,
    eligible_only: bool = False,
) -> int:
    """Insert `account_type`/`currency` for every tenant user missing it.

    Args:
        eligible_only: When True, only users whose `user_type` resolves to the
            Retail or Business category get a row (spec D4).
    """
    users_stmt = select(User.id, User.user_type).where(
        User.tenant_id == tenant_id,
        ~User.id.in_(
            select(Account.user_id).where(
                Account.tenant_id == tenant_id,
                Account.account_type == account_type,
                Account.currency == currency,
                Account.user_id.is_not(None),
            )
        ),
    )
    rows = (await session.execute(users_stmt)).all()

    added = 0
    for user_id, user_type in rows:
        if eligible_only and not await is_commission_wallet_eligible(
            session, tenant_id, user_type
        ):
            continue
        session.add(
            Account(
                tenant_id=tenant_id,
                user_id=user_id,
                account_type=account_type,
                currency=currency,
            )
        )
        added += 1
    return added
```

Add these imports at the top of the file:

```python
from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import ACCOUNT_TYPE_COMMISSION_WALLET, Tenant
```

`is_commission_wallet_eligible` issues one query per distinct user. If the
backfill is slow on a large tenant, cache the category lookup per `user_type`
in a local dict — but only after measuring, per the B1.9 discipline.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/instruments/test_commission_wallet_backfill.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the instruments suite for regressions**

```bash
pytest tests/instruments -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/instruments/service.py \
  backend/tests/instruments/test_commission_wallet_backfill.py
git commit -m "feat(instruments): backfill commission wallets on new financial currency"
```

---

## Task 10: Provision on type change

**Files:**
- Modify: `backend/app/modules/identity/service.py` (in `update_user`, after the `user_type` write)
- Test: `backend/tests/identity/test_type_change_provisioning.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/identity/test_type_change_provisioning.py`:

```python
"""Type change into an eligible category provisions; out of it retains (spec §6.3).

Retention on the way out is not laziness: the ledger is append-only and the
balance may be non-zero, so the wallet must survive to stay disbursable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Instrument,
    Tenant,
    User,
)


async def _has_commission_wallet(session: AsyncSession, user: User) -> bool:
    row = (
        await session.execute(
            select(Account).where(
                Account.user_id == user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalar_one_or_none()
    return row is not None


@pytest.mark.asyncio
async def test_promotion_into_retail_provisions(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, admin_principal
) -> None:
    from app.modules.identity.schemas import UserUpdateRequest
    from app.modules.identity.service import update_user

    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "subscriber"
    db_session.add(
        Instrument(
            tenant_id=test_tenant.id,
            code="ZAR",
            symbol="R",
            display_name="Rand",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        )
    )
    await db_session.commit()
    assert not await _has_commission_wallet(db_session, test_user)

    await update_user(
        db_session,
        test_tenant.id,
        test_user.id,
        UserUpdateRequest(user_type="agent"),
        admin=admin_principal,
    )

    assert await _has_commission_wallet(db_session, test_user)


@pytest.mark.asyncio
async def test_demotion_out_of_retail_retains_the_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, admin_principal
) -> None:
    from app.modules.identity.schemas import UserUpdateRequest
    from app.modules.identity.service import update_user

    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    db_session.add(
        Instrument(
            tenant_id=test_tenant.id,
            code="ZAR",
            symbol="R",
            display_name="Rand",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        )
    )
    await db_session.commit()

    from app.modules.accounts.provisioning import provision_user_accounts

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()
    assert await _has_commission_wallet(db_session, test_user)

    await update_user(
        db_session,
        test_tenant.id,
        test_user.id,
        UserUpdateRequest(user_type="subscriber"),
        admin=admin_principal,
    )

    assert await _has_commission_wallet(db_session, test_user)
```

Match `update_user`'s signature and `UserUpdateRequest`'s fields against
`backend/app/modules/identity/service.py:778` and the existing identity tests.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/identity/test_type_change_provisioning.py -v
```

Expected: `test_promotion_into_retail_provisions` FAILS — no wallet appears.
`test_demotion_out_of_retail_retains_the_wallet` should already PASS (nothing
deletes accounts); it is a regression guard, so keep it.

- [ ] **Step 3: Provision after the type write**

In `update_user`, after `user.user_type` is assigned and before the commit:

```python
    # A promotion into Retail / Business earns a commission wallet (spec §6.3).
    # Deliberately one-directional: a demotion RETAINS the wallet, because the
    # ledger is append-only and its balance may be non-zero — it must stay
    # disbursable. New accruals stop on their own once config no longer resolves.
    from app.modules.accounts.provisioning import provision_user_accounts

    await provision_user_accounts(session, tenant_id=tenant_id, user_id=user.id)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/identity/test_type_change_provisioning.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/identity/service.py \
  backend/tests/identity/test_type_change_provisioning.py
git commit -m "feat(identity): provision commission wallets on type promotion"
```

---

## Task 11: Retrofit script

Because the tenant flag is immutable (D3), this script is the **only** path by
which an existing tenant adopts commission wallets. It is an operator action,
run deliberately, and it must say what it did.

**Files:**
- Create: `backend/scripts/backfill_commission_wallets.py`
- Test: `backend/tests/accounts/test_backfill_script.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/accounts/test_backfill_script.py`:

```python
"""The retrofit script provisions eligible users and is safe to re-run (spec §6.4)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Instrument,
    Tenant,
    User,
)
from scripts.backfill_commission_wallets import backfill_tenant


@pytest.mark.asyncio
async def test_backfill_provisions_and_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    db_session.add(
        Instrument(
            tenant_id=test_tenant.id,
            code="ZAR",
            symbol="R",
            display_name="Rand",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        )
    )
    await db_session.commit()

    first = await backfill_tenant(db_session, test_tenant.id)
    await db_session.commit()
    second = await backfill_tenant(db_session, test_tenant.id)
    await db_session.commit()

    assert first > 0
    assert second == 0

    rows = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_backfill_refuses_a_flag_off_tenant(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """The script provisions; it does not silently enable the feature."""
    test_tenant.commission_wallet_enabled = False
    test_user.user_type = "agent"
    await db_session.commit()

    with pytest.raises(ValueError, match="commission_wallet_enabled"):
        await backfill_tenant(db_session, test_tenant.id)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/accounts/test_backfill_script.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill_commission_wallets'`.

- [ ] **Step 3: Write the script**

Create `backend/scripts/backfill_commission_wallets.py`:

```python
"""Retrofit commission wallets onto an existing tenant's users.

`tenants.commission_wallet_enabled` is creation-time only (spec D3), so this
script is the ONLY path by which a tenant created before the commission-wallet
edition adopts the feature. It is a deliberate operator action, not a product
feature — flip the column by hand first, then run this.

A script rather than a migration (B4.8 precedent): it is per-tenant, re-runnable,
and must not gate a deployment.

Usage:
    python scripts/backfill_commission_wallets.py <tenant_id>
"""

from __future__ import annotations

import asyncio
import sys
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.provisioning import provision_user_accounts
from app.shared.db import async_session_factory
from app.shared.models import Tenant, User


async def backfill_tenant(session: AsyncSession, tenant_id: UUID) -> int:
    """Provision every eligible user in one tenant. Returns rows added.

    Raises:
        ValueError: the tenant does not exist, or its
            `commission_wallet_enabled` flag is off. The script provisions
            wallets; it deliberately does NOT enable the feature, so that
            turning the feature on stays an explicit, auditable act.
    """
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise ValueError(f"Tenant {tenant_id} not found")
    if not tenant.commission_wallet_enabled:
        raise ValueError(
            f"Tenant {tenant_id} has commission_wallet_enabled = false. "
            "Set it before running this backfill."
        )

    user_ids = list(
        (
            await session.execute(select(User.id).where(User.tenant_id == tenant_id))
        ).scalars().all()
    )

    total = 0
    for user_id in user_ids:
        total += await provision_user_accounts(
            session, tenant_id=tenant_id, user_id=user_id
        )
    return total


async def _main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/backfill_commission_wallets.py <tenant_id>")
        raise SystemExit(2)

    tenant_id = UUID(sys.argv[1])
    async with async_session_factory() as session:
        added = await backfill_tenant(session, tenant_id)
        await session.commit()
    print(f"Provisioned {added} account(s) for tenant {tenant_id}.")


if __name__ == "__main__":
    asyncio.run(_main())
```

Match the session-factory import against what `backend/scripts/seed.py` uses —
if it imports something other than `app.shared.db.async_session_factory`, use
that instead.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/accounts/test_backfill_script.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill_commission_wallets.py \
  backend/tests/accounts/test_backfill_script.py
git commit -m "feat(scripts): add commission wallet retrofit backfill"
```

---

## Task 12: Admin user detail — label and exclude from spendable

**Files:**
- Modify: `backend/app/modules/identity/service.py:875-955` (the admin user-detail payload)
- Test: `backend/tests/identity/test_user_detail_commission_balance.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/identity/test_user_detail_commission_balance.py`:

```python
"""Admin user detail separates accrued commission from spendable balance (spec §10).

The account list already enumerates every type generically, so the wallet shows
up for free. What must NOT happen is it being counted as spendable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


@pytest.mark.asyncio
async def test_commission_balance_is_reported_and_not_spendable(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    from app.modules.identity.service import get_user_detail

    for account_type in (ACCOUNT_TYPE_FINANCIAL_WALLET, ACCOUNT_TYPE_COMMISSION_WALLET):
        db_session.add(
            Account(
                tenant_id=test_tenant.id,
                user_id=test_user.id,
                account_type=account_type,
                currency="ZAR",
            )
        )
    await db_session.commit()

    detail = await get_user_detail(db_session, test_tenant.id, test_user.id)

    types = {a["account_type"] for a in detail["accounts"]}
    assert ACCOUNT_TYPE_COMMISSION_WALLET in types

    commission = next(
        a for a in detail["accounts"] if a["account_type"] == ACCOUNT_TYPE_COMMISSION_WALLET
    )
    assert commission["spendable"] is False

    main = next(
        a for a in detail["accounts"] if a["account_type"] == ACCOUNT_TYPE_FINANCIAL_WALLET
    )
    assert main["spendable"] is True
    assert detail["spendable_total"]["ZAR"] == Decimal("0")
```

Read `get_user_detail`'s actual name and return shape at
`backend/app/modules/identity/service.py:875` and match it — if it returns a
Pydantic model rather than a dict, assert against attributes instead of keys.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/identity/test_user_detail_commission_balance.py -v
```

Expected: FAIL — `KeyError: 'spendable'`.

- [ ] **Step 3: Add the spendable flag and total**

In the account-payload loop (currently around `:914`), add a `spendable` key
derived from the account type, and accumulate a per-currency spendable total:

```python
    from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET

    spendable_total: dict[str, Decimal] = {}
    for acct in accounts:
        balance, reserved = await derive_balance(session, acct.id)
        # Spendable is an explicit account-type test, NOT "has a balance":
        # a commission wallet holds real money the user cannot transact against
        # until a disbursement run moves it (spec §5, §10).
        spendable = acct.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET
        if spendable:
            spendable_total[acct.currency] = (
                spendable_total.get(acct.currency, Decimal("0")) + balance
            )
        account_payload.append(
            {
                "account_type": acct.account_type,
                "spendable": spendable,
                # ... existing keys unchanged
            }
        )
```

Add `"spendable_total": spendable_total` to the returned payload, and mirror
both fields into the response schema in
`backend/app/modules/identity/schemas.py`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/identity/test_user_detail_commission_balance.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/identity/ \
  backend/tests/identity/test_user_detail_commission_balance.py
git commit -m "feat(identity): report commission balance as non-spendable"
```

---

## Task 13: Full verification

- [ ] **Step 1: Run the whole backend suite**

```bash
cd backend && make test
```

Expected: all pass. `tests/invariants/test_ledger_sum_to_zero.py` in particular
must still pass — it is the structural guard on every ledger write this plan
touches.

- [ ] **Step 2: Run lint, types and migration drift**

```bash
make check
```

Expected: `alembic check` reports no drift, `ruff` clean, `mypy` clean.

- [ ] **Step 3: Seed a flag-on tenant and eyeball it**

Extend `backend/scripts/seed.py` with a `commission_wallet_enabled=True` tenant
holding at least one agent with a parent super-agent, then:

```bash
make seed
```

Expected: no errors; the agent and super-agent each hold a ZAR main wallet and a
ZAR commission wallet. Plan 2 relies on this seed data.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/seed.py
git commit -m "chore(seed): add a commission-wallet tenant with an agent hierarchy"
```

---

## Done when

- Every user created through any of the three paths holds a main wallet
- Retail/Business users on flag-on tenants also hold a commission wallet per financial currency
- Adding a currency backfills both wallet kinds for existing eligible users
- A commission wallet accepts an unlimited credit and refuses an overdrawing debit with `insufficient_commission_balance`
- The tenant flag cannot be changed after creation
- `CLAUDE.md` and `.claude/rules/ledger-invariants.md` document the third guard shape
- `make test` and `make check` are green

**Next:** Plan 2 (`2026-08-26-commission-wallets-2-payout.md`) — commission config columns, destination resolution, parent commission and tax.
