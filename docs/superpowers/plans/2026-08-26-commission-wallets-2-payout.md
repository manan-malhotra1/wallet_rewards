# Commission Wallets — Plan 2 of 3: Payout

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a commission rule choose where the commission lands (main wallet or commission wallet), and pay the earner's parent a second commission from the same rule.

**Architecture:** Four columns on `commission_configs` carry both the destination and the parent's rate, so one row resolves both legs with the band and precedence logic already in place. `calculate_commission` stops returning a bare `Decimal` and returns a result object naming both amounts, the destination and any parent-skip reason. The charge assembler grows a second pool-debit/parent-credit pair, taxed on the same axis as the child's.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, pytest / pytest-asyncio, Next.js 16 admin UI.

**Spec:** `docs/superpowers/specs/2026-08-26-commission-wallet-design.md` — §4.3, §4.4, §7, §11. Decisions D6–D11.

**Depends on:** Plan 1 complete and merged. Nothing here works without `commission_wallet` accounts existing.

---

## Prerequisites

Read before starting:
- Spec §7 in full
- `backend/app/modules/pricing/assembler.py` — the whole file, it is short and this plan doubles one of its blocks
- `backend/app/modules/commissions/service.py:84` `calculate_commission`
- `docs/superpowers/specs/2026-07-12-pricing-v2-design.md` §Phase 2 D4 — the deferral this plan closes

After Plan 1 the Alembic head is `0066`. This plan adds `0067`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/shared/models/commissions.py` | **Modify** — four new columns and their CHECKs |
| `backend/app/shared/models/ledger.py` | **Modify** — `transactions.parent_commission_amount` |
| `backend/app/modules/commissions/schemas.py` | **Modify** — destination + required parent fields |
| `backend/app/modules/commissions/service.py` | **Modify** — `CommissionOutcome`, parent resolution, D7 config validation |
| `backend/app/modules/commissions/resolution.py` | **Create** — parent lookup and eligibility, kept out of `service.py` so the CRUD half stays readable |
| `backend/app/modules/taxes/service.py` | **Modify** — tax the parent leg independently |
| `backend/app/modules/pricing/assembler.py` | **Modify** — the parent leg |
| `backend/app/modules/{cashin,cashout,external}/service.py` | **Modify** — consume the result object |
| `backend/alembic/versions/20260826_0067_parent_commission_and_destination.py` | **Create** |
| `admin-ui/app/(authenticated)/pricing/_components/commission-config-dialog.tsx` | **Modify** — destination dropdown + parent fields |

`resolution.py` is separate because `service.py` is already 364 lines of
CRUD-plus-math; adding parent walking, category checks and wallet lookup to it
would push it past the point where it can be held in context at once.

---

## Task 1: Schema columns and migration

**Files:**
- Modify: `backend/app/shared/models/commissions.py`
- Modify: `backend/app/shared/models/ledger.py`
- Create: `backend/alembic/versions/20260826_0067_parent_commission_and_destination.py`
- Test: `backend/tests/commissions/test_commission_config_columns.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commissions/test_commission_config_columns.py`:

```python
"""Destination and parent-rate columns persist with the right defaults (spec §4.3).

The DB defaults exist ONLY so migration 0067 can backfill existing rows to
today's behaviour: main wallet, no parent commission. Nothing may reprice on
deploy (D18).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import CommissionConfig, Tenant


@pytest.mark.asyncio
async def test_defaults_reproduce_todays_behaviour(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    config = CommissionConfig(
        tenant_id=test_tenant.id,
        transaction_type="cash_in",
        currency="ZAR",
        user_type="agent",
        fixed_commission=Decimal("1"),
        variable_commission_pct=Decimal("0.01"),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    assert config.payout_destination == "main_wallet"
    assert Decimal(str(config.parent_fixed_commission)) == Decimal("0")
    assert Decimal(str(config.parent_variable_commission_pct)) == Decimal("0")
    assert config.parent_commission_cap is None


@pytest.mark.asyncio
async def test_parent_rates_persist(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    config = CommissionConfig(
        tenant_id=test_tenant.id,
        transaction_type="cash_in",
        currency="ZAR",
        user_type="agent",
        fixed_commission=Decimal("1"),
        variable_commission_pct=Decimal("0.01"),
        payout_destination="commission_wallet",
        parent_fixed_commission=Decimal("0.5"),
        parent_variable_commission_pct=Decimal("0.005"),
        parent_commission_cap=Decimal("20"),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    assert config.payout_destination == "commission_wallet"
    assert Decimal(str(config.parent_variable_commission_pct)) == Decimal("0.005")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commissions/test_commission_config_columns.py -v
```

Expected: FAIL — `TypeError: 'payout_destination' is an invalid keyword argument`.

- [ ] **Step 3: Add the columns to the model**

In `backend/app/shared/models/commissions.py`, add to `CommissionConfig`:

```python
    # Where the commission lands (spec D6). 'main_wallet' reproduces the
    # pre-2026-08-26 behaviour exactly, which is why it is the server default:
    # migration 0067 backfills every existing row to it and nothing reprices.
    payout_destination: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="main_wallet"
    )
    # The earner's PARENT is paid from the SAME row, using the same amount band
    # and precedence (spec D8). The rate is a percentage of the TRANSACTION
    # AMOUNT, not of the child's commission — symmetric with the child terms,
    # which is what lets both legs share one resolver.
    parent_fixed_commission: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    parent_variable_commission_pct: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, server_default="0"
    )
    parent_commission_cap: Mapped[float | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
```

Add to `__table_args__`:

```python
        CheckConstraint(
            "payout_destination IN ('main_wallet', 'commission_wallet')",
            name="ck_commission_configs_payout_destination",
        ),
        CheckConstraint(
            "parent_fixed_commission >= 0",
            name="ck_commission_configs_parent_fixed_nonneg",
        ),
        CheckConstraint(
            "parent_variable_commission_pct >= 0 AND parent_variable_commission_pct < 1",
            name="ck_commission_configs_parent_variable_pct_range",
        ),
```

- [ ] **Step 4: Add the transaction column**

In `backend/app/shared/models/ledger.py`, on `Transaction`, next to
`commission_amount`:

```python
    # Commission paid to the earner's PARENT (spec §4.4). Display-only, like
    # commission_amount — the money itself is in the ledger legs.
    parent_commission_amount: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260826_0067_parent_commission_and_destination.py`:

```python
"""Commission payout destination + parent commission terms.

Spec: docs/superpowers/specs/2026-08-26-commission-wallet-design.md §4.3, §4.4.

Every existing commission_configs row backfills to payout_destination =
'main_wallet' with zero parent terms, which is exactly today's behaviour — no
commission reprices on deploy (D18).

Revision ID: 0067
Revises: 0066
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commission_configs",
        sa.Column(
            "payout_destination",
            sa.String(length=20),
            nullable=False,
            server_default="main_wallet",
        ),
    )
    op.add_column(
        "commission_configs",
        sa.Column(
            "parent_fixed_commission",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "commission_configs",
        sa.Column(
            "parent_variable_commission_pct",
            sa.Numeric(8, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "commission_configs",
        sa.Column("parent_commission_cap", sa.Numeric(20, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_commission_configs_payout_destination",
        "commission_configs",
        "payout_destination IN ('main_wallet', 'commission_wallet')",
    )
    op.create_check_constraint(
        "ck_commission_configs_parent_fixed_nonneg",
        "commission_configs",
        "parent_fixed_commission >= 0",
    )
    op.create_check_constraint(
        "ck_commission_configs_parent_variable_pct_range",
        "commission_configs",
        "parent_variable_commission_pct >= 0 AND parent_variable_commission_pct < 1",
    )
    op.add_column(
        "transactions",
        sa.Column(
            "parent_commission_amount",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "parent_commission_amount")
    op.drop_constraint(
        "ck_commission_configs_parent_variable_pct_range",
        "commission_configs",
        type_="check",
    )
    op.drop_constraint(
        "ck_commission_configs_parent_fixed_nonneg", "commission_configs", type_="check"
    )
    op.drop_constraint(
        "ck_commission_configs_payout_destination", "commission_configs", type_="check"
    )
    op.drop_column("commission_configs", "parent_commission_cap")
    op.drop_column("commission_configs", "parent_variable_commission_pct")
    op.drop_column("commission_configs", "parent_fixed_commission")
    op.drop_column("commission_configs", "payout_destination")
```

- [ ] **Step 6: Apply and verify no drift**

```bash
alembic upgrade head && python scripts/check_migrations.py
```

Expected: no drift.

- [ ] **Step 7: Run the test to verify it passes**

```bash
pytest tests/commissions/test_commission_config_columns.py -v
```

Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/shared/models/commissions.py backend/app/shared/models/ledger.py \
  backend/alembic/versions/20260826_0067_parent_commission_and_destination.py \
  backend/tests/commissions/test_commission_config_columns.py
git commit -m "feat(commissions): add payout destination and parent commission columns"
```

---

## Task 2: Config-write validation (D7)

The destination dropdown must be impossible to misuse from the API, not merely
absent from the UI.

**Files:**
- Modify: `backend/app/modules/commissions/schemas.py`
- Modify: `backend/app/modules/commissions/service.py`
- Modify: `backend/app/shared/exceptions/__init__.py`
- Test: `backend/tests/commissions/test_destination_validation.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commissions/test_destination_validation.py`:

```python
"""A commission-wallet destination is only configurable where it can exist (D7).

Three ways a rule could name a destination that has no wallet behind it:
tenant flag off, catch-all (NULL) user_type that could match a consumer, or a
consumer-category type. All three are refused AT CONFIG WRITE, so the payout
path never has to resolve an impossible rule.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import create_commission_config
from app.shared.exceptions import CommissionDestinationNotAvailable
from app.shared.models import Tenant


def _request(tenant_id, **overrides) -> CommissionConfigCreateRequest:
    payload = {
        "tenant_id": tenant_id,
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "fixed_commission": Decimal("1"),
        "variable_commission_pct": Decimal("0.01"),
        "payout_destination": "commission_wallet",
        "parent_fixed_commission": Decimal("0"),
        "parent_variable_commission_pct": Decimal("0"),
    }
    payload.update(overrides)
    return CommissionConfigCreateRequest(**payload)


@pytest.mark.asyncio
async def test_refused_when_tenant_flag_is_off(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    test_tenant.commission_wallet_enabled = False
    await db_session.commit()

    with pytest.raises(CommissionDestinationNotAvailable):
        await create_commission_config(db_session, _request(test_tenant.id))


@pytest.mark.asyncio
async def test_refused_for_a_catch_all_band(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A NULL user_type could match a consumer, who never has the wallet."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    with pytest.raises(CommissionDestinationNotAvailable):
        await create_commission_config(db_session, _request(test_tenant.id, user_type=None))


@pytest.mark.asyncio
async def test_refused_for_a_consumer_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    with pytest.raises(CommissionDestinationNotAvailable):
        await create_commission_config(
            db_session, _request(test_tenant.id, user_type="subscriber")
        )


@pytest.mark.asyncio
async def test_allowed_for_a_retail_type_on_a_flag_on_tenant(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()

    config = await create_commission_config(db_session, _request(test_tenant.id))
    assert config.payout_destination == "commission_wallet"


@pytest.mark.asyncio
async def test_main_wallet_destination_is_always_allowed(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A catch-all main-wallet rule stays legal — today's behaviour is untouched."""
    test_tenant.commission_wallet_enabled = False
    await db_session.commit()

    config = await create_commission_config(
        db_session,
        _request(test_tenant.id, user_type=None, payout_destination="main_wallet"),
    )
    assert config.payout_destination == "main_wallet"


@pytest.mark.asyncio
async def test_parent_terms_are_required(test_tenant: Tenant) -> None:
    """Zero is a decision the admin must make, not an omission (D8)."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        CommissionConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="cash_in",
            currency="ZAR",
            user_type="agent",
            fixed_commission=Decimal("1"),
            variable_commission_pct=Decimal("0.01"),
            payout_destination="main_wallet",
            # parent_* deliberately omitted
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commissions/test_destination_validation.py -v
```

Expected: FAIL — `ImportError: cannot import name 'CommissionDestinationNotAvailable'`.

- [ ] **Step 3: Add the exception**

In `backend/app/shared/exceptions/__init__.py`:

```python
class CommissionDestinationNotAvailable(AppHTTPException):
    """A rule named the commission wallet where no such wallet can exist (D7).

    Raised at config write for three cases: the tenant flag is off; the rule is
    a catch-all (NULL user_type) band that could match a consumer; or the rule
    is scoped to a consumer-category type. Refusing here rather than at payout
    means an unpayable rule can never be saved, so the payout path's
    missing-wallet branch is a backstop rather than a live code path.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "commission_destination_not_available",
            "Commission wallets are not available for this tenant and user type.",
        )
```

- [ ] **Step 4: Add the schema fields**

In `backend/app/modules/commissions/schemas.py`, on `CommissionConfigCreateRequest`:

```python
    payout_destination: Literal["main_wallet", "commission_wallet"] = "main_wallet"
    # Required with NO default (spec D8): the admin must state the parent rate
    # even when it is zero. A default here would let a caller silently ship a
    # rule whose parent leg pays nothing when they meant it to pay something.
    parent_fixed_commission: Decimal = Field(ge=Decimal("0"))
    parent_variable_commission_pct: Decimal = Field(ge=Decimal("0"), lt=Decimal("1"))
    parent_commission_cap: Decimal | None = Field(default=None, ge=Decimal("0"))
```

Import `Literal` from `typing` if not already imported.

- [ ] **Step 5: Enforce D7 in the service**

In `backend/app/modules/commissions/service.py`, add:

```python
async def _assert_destination_available(
    session: AsyncSession, request: CommissionConfigCreateRequest
) -> None:
    """Refuse a commission-wallet destination that cannot resolve to a wallet (D7).

    Checked BEFORE any write, and before the band replace deletes anything, so
    a bad payload never wipes a live band set.

    Raises:
        CommissionDestinationNotAvailable: 422 — flag off, catch-all band, or a
            consumer-category type.
    """
    if request.payout_destination != "commission_wallet":
        return

    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == request.tenant_id))
    ).scalar_one_or_none()
    if tenant is None or not tenant.commission_wallet_enabled:
        raise CommissionDestinationNotAvailable()

    # A NULL user_type band applies to EVERY type including consumers, who never
    # hold a commission wallet. Rather than resolving that per-earner at payout,
    # forbid the combination outright.
    if request.user_type is None:
        raise CommissionDestinationNotAvailable()

    if not await is_commission_wallet_eligible(
        session, request.tenant_id, request.user_type
    ):
        raise CommissionDestinationNotAvailable()
```

Call it in `create_commission_config` immediately after
`assert_optional_user_type_valid`, and in `replace_commission_config_for_scope`
immediately after its own `assert_optional_user_type_valid` call — before the
deletes, for the reason in the docstring.

Extend `_new_commission_config` to copy the four new fields, and
`_commission_config_state` to include them in the audit snapshot (Decimals as
`str`, matching the existing style).

Add imports: `CommissionDestinationNotAvailable`,
`is_commission_wallet_eligible`, `Tenant`.

- [ ] **Step 6: Run the test to verify it passes**

```bash
pytest tests/commissions/test_destination_validation.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Run the commissions suite for regressions**

```bash
pytest tests/commissions -v
```

Expected: all pass. Existing tests that build a `CommissionConfigCreateRequest`
must be updated to supply the now-required parent fields — that is expected
churn, not a failure to work around by giving the fields a default.

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/commissions/ backend/app/shared/exceptions/__init__.py \
  backend/tests/commissions/
git commit -m "feat(commissions): validate payout destination at config write"
```

---

## Task 3: Parent resolution

**Files:**
- Create: `backend/app/modules/commissions/resolution.py`
- Test: `backend/tests/commissions/test_parent_resolution.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commissions/test_parent_resolution.py`:

```python
"""Parent resolution: exactly one level, fail-open with a reason (D9, D10).

A standalone agent with no super-agent is the NORMAL case, not an error. It
must never block their cash-in — so every unpayable-parent path returns a
reason rather than raising.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.resolution import resolve_parent_target
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


async def _user(session: AsyncSession, tenant: Tenant, user_type: str, parent=None) -> User:
    user = User(
        tenant_id=tenant.id,
        user_type=user_type,
        parent_user_id=parent.id if parent is not None else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _wallet(session: AsyncSession, tenant: Tenant, user: User, account_type: str) -> Account:
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=account_type,
        currency="ZAR",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_no_parent_returns_a_reason(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    agent = await _user(db_session, test_tenant, "agent")

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "no_parent"


@pytest.mark.asyncio
async def test_eligible_parent_resolves_to_their_commission_wallet(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    parent = await _user(db_session, test_tenant, "super_agent")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    wallet = await _wallet(db_session, test_tenant, parent, ACCOUNT_TYPE_COMMISSION_WALLET)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id == wallet.id
    assert target.skip_reason is None


@pytest.mark.asyncio
async def test_parent_leg_follows_the_child_destination(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Main-wallet rules pay the parent into their MAIN wallet (D6 + spec §7.2)."""
    parent = await _user(db_session, test_tenant, "super_agent")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    main = await _wallet(db_session, test_tenant, parent, ACCOUNT_TYPE_FINANCIAL_WALLET)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="main_wallet",
        currency="ZAR",
    )
    assert target.account_id == main.id


@pytest.mark.asyncio
async def test_consumer_parent_is_skipped(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    parent = await _user(db_session, test_tenant, "subscriber")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    await _wallet(db_session, test_tenant, parent, ACCOUNT_TYPE_FINANCIAL_WALLET)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "parent_ineligible_category"


@pytest.mark.asyncio
async def test_parent_without_the_wallet_is_skipped(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    parent = await _user(db_session, test_tenant, "super_agent")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "parent_wallet_missing"


@pytest.mark.asyncio
async def test_grandparent_is_never_walked(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Exactly one level (D9) — the two-level cap from user-types D7."""
    grandparent = await _user(db_session, test_tenant, "super_agent")
    parent = await _user(db_session, test_tenant, "super_agent", parent=grandparent)
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    gp_wallet = await _wallet(
        db_session, test_tenant, grandparent, ACCOUNT_TYPE_COMMISSION_WALLET
    )
    parent_wallet = await _wallet(
        db_session, test_tenant, parent, ACCOUNT_TYPE_COMMISSION_WALLET
    )

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id == parent_wallet.id
    assert target.account_id != gp_wallet.id
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commissions/test_parent_resolution.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.commissions.resolution'`.

- [ ] **Step 3: Implement resolution**

Create `backend/app/modules/commissions/resolution.py`:

```python
"""Commission payout targets — which account each leg credits.

Split out of `service.py` so the CRUD half stays readable: this module owns
parent walking, category eligibility and wallet lookup, and `service.py` owns
config maths and admin CRUD.

Every unpayable-parent path returns a REASON rather than raising (spec D10).
A standalone agent with no super-agent is the normal case, and must never
block their cash-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import is_commission_wallet_eligible
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    User,
)

# Skip reasons recorded on the transaction when the parent leg does not pay.
SKIP_NO_PARENT = "no_parent"
SKIP_PARENT_INELIGIBLE = "parent_ineligible_category"
SKIP_PARENT_WALLET_MISSING = "parent_wallet_missing"
SKIP_PARENT_ZERO_RATE = "parent_zero_rate"


@dataclass(frozen=True)
class PayoutTarget:
    """One commission leg's destination.

    Attributes:
        account_id: The account to CREDIT, or None when the leg does not pay.
        skip_reason: Why it does not pay. None when `account_id` is set.
    """

    account_id: UUID | None
    skip_reason: str | None


def _account_type_for(destination: str) -> str:
    """Map a config destination to the account type that receives the credit."""
    return (
        ACCOUNT_TYPE_COMMISSION_WALLET
        if destination == "commission_wallet"
        else ACCOUNT_TYPE_FINANCIAL_WALLET
    )


async def _find_wallet(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, account_type: str, currency: str
) -> Account | None:
    """Return one user's account of a type/currency, or None."""
    return (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == account_type,
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one_or_none()


async def resolve_earner_target(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    earner_user_id: UUID,
    destination: str,
    currency: str,
) -> PayoutTarget:
    """Resolve where the EARNER's own commission is credited.

    Unlike the parent leg this does NOT fail open: a missing account here means
    a rule was configured for a user who cannot receive it, and the caller must
    422 before any ledger write (spec §7.2, invariant #12 discipline).
    """
    account = await _find_wallet(
        session,
        tenant_id=tenant_id,
        user_id=earner_user_id,
        account_type=_account_type_for(destination),
        currency=currency,
    )
    if account is None:
        return PayoutTarget(None, SKIP_PARENT_WALLET_MISSING)
    return PayoutTarget(account.id, None)


async def resolve_parent_target(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    earner_user_id: UUID,
    destination: str,
    currency: str,
) -> PayoutTarget:
    """Resolve where the earner's PARENT commission is credited.

    Walks EXACTLY ONE level via `users.parent_user_id` — never a chain (D9),
    consistent with the two-level type-hierarchy cap (user-types D7).

    The parent leg lands in the same KIND of wallet the child's rule names
    (D6): a commission-wallet rule holds the parent's share for review too.

    Returns:
        A PayoutTarget whose `skip_reason` is set for every unpayable case.
        Never raises — that is what fail-open means here.
    """
    earner = (
        await session.execute(
            select(User).where(User.id == earner_user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if earner is None or earner.parent_user_id is None:
        return PayoutTarget(None, SKIP_NO_PARENT)

    parent = (
        await session.execute(
            select(User).where(
                User.id == earner.parent_user_id, User.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        return PayoutTarget(None, SKIP_NO_PARENT)

    # Impossible by construction (the hierarchy validation at user create plus
    # ck_user_types_no_self_parent), asserted anyway per spec §7.1.
    assert parent.id != earner_user_id, "parent_user_id must never be self"

    if not await is_commission_wallet_eligible(session, tenant_id, parent.user_type):
        return PayoutTarget(None, SKIP_PARENT_INELIGIBLE)

    account = await _find_wallet(
        session,
        tenant_id=tenant_id,
        user_id=parent.id,
        account_type=_account_type_for(destination),
        currency=currency,
    )
    if account is None:
        return PayoutTarget(None, SKIP_PARENT_WALLET_MISSING)
    return PayoutTarget(account.id, None)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commissions/test_parent_resolution.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commissions/resolution.py \
  backend/tests/commissions/test_parent_resolution.py
git commit -m "feat(commissions): resolve earner and parent payout targets"
```

---

## Task 4: `calculate_commission` returns an outcome

**Files:**
- Modify: `backend/app/modules/commissions/service.py:84`
- Test: `backend/tests/commissions/test_commission_outcome.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/commissions/test_commission_outcome.py`:

```python
"""calculate_commission returns both legs, the destination and any skip reason.

The parent rate is a percentage of the TRANSACTION AMOUNT (D8), NOT of the
child's commission — assert on a case where the two would differ.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.service import calculate_commission
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    Account,
    CommissionConfig,
    Tenant,
    User,
)


async def _config(session: AsyncSession, tenant: Tenant, **overrides) -> CommissionConfig:
    payload = {
        "tenant_id": tenant.id,
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "fixed_commission": Decimal("0"),
        "variable_commission_pct": Decimal("0.01"),
        "payout_destination": "commission_wallet",
        "parent_fixed_commission": Decimal("0"),
        "parent_variable_commission_pct": Decimal("0.005"),
    }
    payload.update(overrides)
    config = CommissionConfig(**payload)
    session.add(config)
    await session.commit()
    return config


async def _agent_with_parent(session: AsyncSession, tenant: Tenant) -> tuple[User, User]:
    parent = User(tenant_id=tenant.id, user_type="super_agent")
    session.add(parent)
    await session.commit()
    await session.refresh(parent)

    agent = User(tenant_id=tenant.id, user_type="agent", parent_user_id=parent.id)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    for user in (agent, parent):
        session.add(
            Account(
                tenant_id=tenant.id,
                user_id=user.id,
                account_type=ACCOUNT_TYPE_COMMISSION_WALLET,
                currency="ZAR",
            )
        )
    await session.commit()
    return agent, parent


@pytest.mark.asyncio
async def test_parent_rate_is_a_percentage_of_the_transaction_amount(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """1% child, 0.5% parent, on R1000: R10 and R5.

    If the parent rate were a share of the CHILD'S COMMISSION it would be
    0.005 * 10 = R0.05. This assertion is what pins D8.
    """
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant)
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await calculate_commission(
        db_session,
        tenant_id=test_tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal("1000"),
    )

    assert outcome.self_amount == Decimal("10.000000")
    assert outcome.parent_amount == Decimal("5.000000")
    assert outcome.destination == "commission_wallet"
    assert outcome.parent_skip_reason is None


@pytest.mark.asyncio
async def test_parent_cap_applies(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant, parent_commission_cap=Decimal("2"))
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await calculate_commission(
        db_session,
        tenant_id=test_tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal("1000"),
    )
    assert outcome.parent_amount == Decimal("2.000000")


@pytest.mark.asyncio
async def test_zero_parent_rate_skips_with_a_reason(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant, parent_variable_commission_pct=Decimal("0"))
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await calculate_commission(
        db_session,
        tenant_id=test_tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal("1000"),
    )
    assert outcome.parent_amount == Decimal("0")
    assert outcome.parent_skip_reason == "parent_zero_rate"


@pytest.mark.asyncio
async def test_no_config_pays_nothing(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Commission stays additive and optional — a missing config is NOT a 422."""
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await calculate_commission(
        db_session,
        tenant_id=test_tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal("1000"),
    )
    assert outcome.self_amount == Decimal("0")
    assert outcome.parent_amount == Decimal("0")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/commissions/test_commission_outcome.py -v
```

Expected: FAIL — `AttributeError: 'decimal.Decimal' object has no attribute 'self_amount'`.

- [ ] **Step 3: Rewrite `calculate_commission`**

In `backend/app/modules/commissions/service.py`, add the result type and replace
the function body:

```python
@dataclass(frozen=True)
class CommissionOutcome:
    """Both commission legs for one transaction, plus where they land.

    Attributes:
        self_amount: The acting earner's own commission, 6 dp.
        parent_amount: Their parent's commission, 6 dp. Zero when skipped.
        destination: 'main_wallet' or 'commission_wallet' — applies to BOTH
            legs (D6). 'main_wallet' when no config resolved.
        parent_account_id: The ACCOUNT the parent's leg credits, or None. An
            account rather than a user id because that is what the caller needs
            to build the ledger leg — resolving it twice would let the two
            resolutions disagree.
        parent_skip_reason: Why the parent leg does not pay, or None.
    """

    self_amount: Decimal
    parent_amount: Decimal
    destination: str
    parent_account_id: UUID | None
    parent_skip_reason: str | None


_NO_COMMISSION = CommissionOutcome(
    self_amount=Decimal("0"),
    parent_amount=Decimal("0"),
    destination="main_wallet",
    parent_account_id=None,
    parent_skip_reason=None,
)


def _band_amount(
    fixed: Decimal, pct: Decimal, cap: Decimal | None, amount: Decimal
) -> Decimal:
    """`fixed + min(pct * amount, cap or +Inf)`, quantized to the ledger's 6 dp.

    Shared by both legs so the child and parent round identically — computing
    them differently is how a three-leg ledger fails to balance by a cent.
    """
    variable = pct * amount
    if cap is not None and variable > cap:
        variable = cap
    return (fixed + variable).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def calculate_commission(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_user_id: UUID,
    transaction_type: str,
    currency: str,
    amount: Decimal,
) -> CommissionOutcome:
    """Compute both commission legs for one transaction.

    The parent's rate is a percentage of the TRANSACTION AMOUNT (D8), resolved
    from the SAME config row and therefore the same amount band and precedence
    as the child's. It is NOT a share of the child's commission.

    A missing config yields `_NO_COMMISSION` rather than raising — commission
    is an additive, optional payout, not a mandatory charge (unchanged from the
    pre-2026-08-26 behaviour).

    Returns:
        A CommissionOutcome. `parent_amount` is zero whenever
        `parent_skip_reason` is set.
    """
    user_type = await resolve_user_type(session, tenant_id, agent_user_id)
    config = await _find_commission_config(
        session,
        tenant_id=tenant_id,
        transaction_type=transaction_type,
        currency=currency,
        user_type=user_type,
        amount=amount,
    )
    if config is None:
        return _NO_COMMISSION

    self_amount = _band_amount(
        Decimal(str(config.fixed_commission)),
        Decimal(str(config.variable_commission_pct)),
        Decimal(str(config.commission_cap)) if config.commission_cap is not None else None,
        amount,
    )
    parent_amount = _band_amount(
        Decimal(str(config.parent_fixed_commission)),
        Decimal(str(config.parent_variable_commission_pct)),
        Decimal(str(config.parent_commission_cap))
        if config.parent_commission_cap is not None
        else None,
        amount,
    )

    if parent_amount <= 0:
        return CommissionOutcome(
            self_amount=self_amount,
            parent_amount=Decimal("0"),
            destination=config.payout_destination,
            parent_account_id=None,
            parent_skip_reason=SKIP_PARENT_ZERO_RATE,
        )

    target = await resolve_parent_target(
        session,
        tenant_id=tenant_id,
        earner_user_id=agent_user_id,
        destination=config.payout_destination,
        currency=currency,
    )
    if target.account_id is None:
        return CommissionOutcome(
            self_amount=self_amount,
            parent_amount=Decimal("0"),
            destination=config.payout_destination,
            parent_account_id=None,
            parent_skip_reason=target.skip_reason,
        )

    return CommissionOutcome(
        self_amount=self_amount,
        parent_amount=parent_amount,
        destination=config.payout_destination,
        parent_account_id=target.account_id,
        parent_skip_reason=None,
    )
```

Add imports: `dataclass` from `dataclasses`, `resolve_parent_target` and
`SKIP_PARENT_ZERO_RATE` from `app.modules.commissions.resolution`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/commissions/test_commission_outcome.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/commissions/service.py \
  backend/tests/commissions/test_commission_outcome.py
git commit -m "feat(commissions): return both legs from calculate_commission"
```

---

## Task 5: Tax the parent leg independently

**Files:**
- Modify: `backend/app/modules/taxes/service.py:31` (`TaxComputation`) and `:68` (`calculate_tax`)
- Test: `backend/tests/taxes/test_parent_commission_tax.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/taxes/test_parent_commission_tax.py`:

```python
"""Parent commission is taxed on the same axis, computed per leg (D11).

Per-leg rather than on the combined total, because rounding a combined figure
and splitting it afterwards does not reconcile against two separate ledger legs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.taxes.service import calculate_tax
from app.shared.models import TaxConfig, Tenant


@pytest.mark.asyncio
async def test_parent_commission_is_taxed_at_the_same_rate(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    db_session.add(
        TaxConfig(
            tenant_id=test_tenant.id,
            currency="ZAR",
            fee_tax_pct=Decimal("0"),
            commission_tax_pct=Decimal("0.15"),
            commission_tax_inclusive=False,
        )
    )
    await db_session.commit()

    tax = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("0"),
        commission=Decimal("10"),
        parent_commission=Decimal("5"),
    )

    assert tax.commission_tax == Decimal("1.500000")
    assert tax.parent_commission_tax == Decimal("0.750000")
    assert tax.commission_tax_inclusive is False


@pytest.mark.asyncio
async def test_zero_parent_commission_is_taxed_zero(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    db_session.add(
        TaxConfig(
            tenant_id=test_tenant.id,
            currency="ZAR",
            fee_tax_pct=Decimal("0"),
            commission_tax_pct=Decimal("0.15"),
        )
    )
    await db_session.commit()

    tax = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("0"),
        commission=Decimal("10"),
        parent_commission=Decimal("0"),
    )
    assert tax.parent_commission_tax == Decimal("0")
```

Match `calculate_tax`'s existing keyword names against
`backend/app/modules/taxes/service.py:68` before running.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/taxes/test_parent_commission_tax.py -v
```

Expected: FAIL — `TypeError: calculate_tax() got an unexpected keyword argument 'parent_commission'`.

- [ ] **Step 3: Extend `TaxComputation` and `calculate_tax`**

In `backend/app/modules/taxes/service.py`, add to `TaxComputation`:

```python
    # Tax on the PARENT's commission (spec D11). Computed on its own base at
    # the same rate, NOT as a share of `commission_tax` — each leg is a separate
    # ledger entry and each must round independently to reconcile.
    parent_commission_tax: Decimal
```

Add a `parent_commission: Decimal = Decimal("0")` keyword parameter to
`calculate_tax`, and next to the existing `commission_tax` computation:

```python
    parent_commission_tax = (
        parent_commission * Decimal(str(config.commission_tax_pct))
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
```

Include it in the returned `TaxComputation`. Give the parameter a default of
zero so the three existing call sites keep compiling until Task 7 updates them.

Where `calculate_tax` returns an all-zero computation because no tax config
resolved, make sure `parent_commission_tax` is zero there too.

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/taxes/test_parent_commission_tax.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the taxes suite for regressions**

```bash
pytest tests/taxes -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/taxes/service.py backend/tests/taxes/test_parent_commission_tax.py
git commit -m "feat(taxes): tax the parent commission leg independently"
```

---

## Task 6: The assembler's parent leg

**Files:**
- Modify: `backend/app/modules/pricing/assembler.py`
- Test: `backend/tests/pricing/test_assembler_parent_leg.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/pricing/test_assembler_parent_leg.py`:

```python
"""The parent leg balances, on both tax axes (spec §7.3, D11).

The whole entries list must sum to zero — that is what post_transaction's
_assert_balanced enforces, and a three-commission-leg transaction is where an
off-by-one in the tax split would first show up.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.modules.pricing.assembler import (
    ChargeAccounts,
    ChargeAmounts,
    ChargeFlags,
    assemble_charges,
)
from app.shared.models import ENTRY_CREDIT, ENTRY_DEBIT

_ZERO = Decimal("0")


def _accounts(parent_account_id=None) -> ChargeAccounts:
    return ChargeAccounts(
        payer_account_id=uuid4(),
        beneficiary_account_id=uuid4(),
        fee_account_id=uuid4(),
        service_tax_account_id=uuid4(),
        commission_tax_account_id=uuid4(),
        commission_pool_account_id=uuid4(),
        agent_account_id=uuid4(),
        parent_account_id=parent_account_id,
    )


def _net(entries) -> Decimal:
    total = _ZERO
    for entry in entries:
        total += entry.amount if entry.entry_type == ENTRY_CREDIT else -entry.amount
    return total


def test_parent_leg_balances_exclusive_tax() -> None:
    parent_account_id = uuid4()
    accounts = _accounts(parent_account_id)
    result = assemble_charges(
        accounts,
        ChargeAmounts(
            principal=Decimal("1000"),
            fee=Decimal("10"),
            commission=Decimal("10"),
            fee_tax=_ZERO,
            commission_tax=Decimal("1.5"),
            parent_commission=Decimal("5"),
            parent_commission_tax=Decimal("0.75"),
        ),
        ChargeFlags(commission_tax_inclusive=False),
    )

    assert _net(result.entries) == _ZERO
    parent_credit = sum(
        e.amount for e in result.entries
        if e.account_id == parent_account_id and e.entry_type == ENTRY_CREDIT
    )
    # Exclusive: the pool funds the tax on top, so the parent nets the full 5.
    assert parent_credit == Decimal("5")
    assert result.parent_commission_amount == Decimal("5")


def test_parent_leg_balances_inclusive_tax() -> None:
    parent_account_id = uuid4()
    accounts = _accounts(parent_account_id)
    result = assemble_charges(
        accounts,
        ChargeAmounts(
            principal=Decimal("1000"),
            fee=Decimal("10"),
            commission=Decimal("10"),
            fee_tax=_ZERO,
            commission_tax=Decimal("1.5"),
            parent_commission=Decimal("5"),
            parent_commission_tax=Decimal("0.75"),
        ),
        ChargeFlags(commission_tax_inclusive=True),
    )

    assert _net(result.entries) == _ZERO
    parent_credit = sum(
        e.amount for e in result.entries
        if e.account_id == parent_account_id and e.entry_type == ENTRY_CREDIT
    )
    # Inclusive: the tax is carved out of the parent's own 5.
    assert parent_credit == Decimal("4.25")


def test_no_parent_emits_no_parent_leg() -> None:
    """A standalone agent's transaction is byte-identical to the old two-leg shape."""
    accounts = _accounts(parent_account_id=None)
    result = assemble_charges(
        accounts,
        ChargeAmounts(
            principal=Decimal("1000"),
            fee=Decimal("10"),
            commission=Decimal("10"),
            fee_tax=_ZERO,
            commission_tax=Decimal("1.5"),
        ),
        ChargeFlags(commission_tax_inclusive=False),
    )

    assert _net(result.entries) == _ZERO
    assert result.parent_commission_amount == _ZERO
```

Match `ChargeAccounts`' existing field names against
`backend/app/modules/pricing/assembler.py:34` before running.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/pricing/test_assembler_parent_leg.py -v
```

Expected: FAIL — `TypeError: ChargeAccounts.__init__() got an unexpected keyword argument 'parent_account_id'`.

- [ ] **Step 3: Extend the dataclasses**

In `backend/app/modules/pricing/assembler.py`:

```python
# On ChargeAccounts:
    # The earner's PARENT wallet — the same KIND of wallet the child's rule
    # names (spec D6). None when the parent leg does not pay: no parent,
    # ineligible category, missing wallet or a zero rate (D10).
    parent_account_id: UUID | None = None

# On ChargeAmounts:
    # `Cp` — the parent's commission, additive from the same pool as `C`.
    parent_commission: Decimal = _ZERO
    # `Tcp` — tax on the parent's commission, on the same axis as `Tc` (D11).
    parent_commission_tax: Decimal = _ZERO

# On AssembledCharges:
    # For the transaction's parent_commission_amount display column.
    parent_commission_amount: Decimal
```

All three new `ChargeAccounts` / `ChargeAmounts` fields carry defaults so the
existing call sites keep compiling until Task 7 updates them.

- [ ] **Step 4: Emit the parent leg**

In `assemble_charges`, after the existing commission block and before the
`return`:

```python
    # --- Parent commission + its tax (spec §7.3) -----------------------------
    # Mirrors the child block exactly, funded from the SAME unguarded pool, and
    # split on the SAME inclusive/exclusive axis. Emitted only when a parent
    # account resolved — `_append_if_positive` would drop zero legs anyway, but
    # the None check keeps a skipped parent from being confused with a zero one.
    cp = amounts.parent_commission
    tcp = amounts.parent_commission_tax

    if accounts.parent_account_id is not None and cp > _ZERO:
        parent_tax_on_top = _ZERO if flags.commission_tax_inclusive else tcp
        parent_pool_debit = cp + parent_tax_on_top
        parent_credit = cp - (tcp if flags.commission_tax_inclusive else _ZERO)

        _append_if_positive(
            entries, accounts.commission_pool_account_id, ENTRY_DEBIT, parent_pool_debit
        )
        _append_if_positive(entries, accounts.parent_account_id, ENTRY_CREDIT, parent_credit)
        _append_if_positive(entries, accounts.commission_tax_account_id, ENTRY_CREDIT, tcp)
    else:
        cp = _ZERO
        tcp = _ZERO
```

Update the return:

```python
    return AssembledCharges(
        entries=entries,
        fee_amount=f,
        commission_amount=c,
        parent_commission_amount=cp,
        tax_amount=tf + tc + tcp,
    )
```

Reassigning `cp`/`tcp` to zero in the `else` branch is what keeps
`parent_commission_amount` and `tax_amount` honest when a parent was skipped
but the caller still passed an amount.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/pricing/test_assembler_parent_leg.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the pricing suite for regressions**

```bash
pytest tests/pricing -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/pricing/assembler.py \
  backend/tests/pricing/test_assembler_parent_leg.py
git commit -m "feat(pricing): assemble the parent commission leg"
```

---

## Task 7: Wire cash-in

**Files:**
- Modify: `backend/app/modules/cashin/service.py:271-400`
- Test: `backend/tests/cashin/test_cashin_commission_destination.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/cashin/test_cashin_commission_destination.py`:

```python
"""Cash-in pays commission where the rule says, and pays the parent (spec §7).

The load-bearing assertion is the third one: the agent's SPENDABLE balance must
be unchanged by a commission-wallet payout. That is the entire point of the
feature — commission that is held for review is not spendable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


async def _wallet_of(
    session: AsyncSession, user: User, account_type: str
) -> Account | None:
    from sqlalchemy import select

    return (
        await session.execute(
            select(Account).where(
                Account.user_id == user.id, Account.account_type == account_type
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_commission_lands_in_the_commission_wallet(
    db_session: AsyncSession, cashin_fixture
) -> None:
    """Build on the existing cash-in fixture; assert the destination only."""
    agent = cashin_fixture.agent
    commission_wallet = await _wallet_of(db_session, agent, ACCOUNT_TYPE_COMMISSION_WALLET)
    main_wallet = await _wallet_of(db_session, agent, ACCOUNT_TYPE_FINANCIAL_WALLET)

    main_before, _ = await derive_balance(db_session, main_wallet.id)

    await cashin_fixture.perform(amount=Decimal("1000"))

    commission_balance, _ = await derive_balance(db_session, commission_wallet.id)
    main_after, _ = await derive_balance(db_session, main_wallet.id)

    assert commission_balance > Decimal("0")
    # The agent funded the customer, so main went DOWN by the principal — but
    # NOT up by any commission.
    assert main_after == main_before - Decimal("1000")


@pytest.mark.asyncio
async def test_parent_is_paid_into_their_commission_wallet(
    db_session: AsyncSession, cashin_fixture
) -> None:
    parent_wallet = await _wallet_of(
        db_session, cashin_fixture.super_agent, ACCOUNT_TYPE_COMMISSION_WALLET
    )
    await cashin_fixture.perform(amount=Decimal("1000"))

    balance, _ = await derive_balance(db_session, parent_wallet.id)
    assert balance > Decimal("0")


@pytest.mark.asyncio
async def test_main_wallet_rules_behave_exactly_as_before(
    db_session: AsyncSession, cashin_fixture
) -> None:
    """Regression guard on D18: existing configs must not change behaviour."""
    await cashin_fixture.set_destination("main_wallet")
    agent = cashin_fixture.agent
    main_wallet = await _wallet_of(db_session, agent, ACCOUNT_TYPE_FINANCIAL_WALLET)
    main_before, _ = await derive_balance(db_session, main_wallet.id)

    await cashin_fixture.perform(amount=Decimal("1000"))

    main_after, _ = await derive_balance(db_session, main_wallet.id)
    # Principal out, commission back in — so the drop is LESS than the principal.
    assert main_after > main_before - Decimal("1000")
```

`cashin_fixture` does not exist yet. Build it in
`backend/tests/cashin/conftest.py` by extracting the setup already duplicated
across the existing cash-in tests — a tenant with the flag on, an agent with a
super-agent parent, both holding main and commission wallets, a funded float, a
pricing config, a limit config, and a commission config with a non-zero parent
rate. Expose `.agent`, `.super_agent`, `.perform(amount)` and
`.set_destination(value)`. Read `backend/tests/cashin/` first and reuse whatever
fixtures already exist rather than duplicating them.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/cashin/test_cashin_commission_destination.py -v
```

Expected: FAIL — commission still lands in the main wallet.

- [ ] **Step 3: Consume the outcome in cash-in**

In `backend/app/modules/cashin/service.py`, replace the commission call
(currently around `:281`) and the account wiring (`:301-330`):

```python
    outcome = await calculate_commission(
        session,
        tenant_id=tenant_id,
        agent_user_id=agent_user_id,
        transaction_type="cash_in",
        currency=currency,
        amount=amount,
    )

    tax = await calculate_tax(
        session,
        tenant_id=tenant_id,
        currency=currency,
        fee=fee,
        commission=outcome.self_amount,
        parent_commission=outcome.parent_amount,
    )

    # Where the earner's own commission lands. Fails CLOSED (spec §7.2): a rule
    # that resolves but has no wallet behind it is an operator error, and paying
    # it into the spendable wallet instead would silently void the review hold.
    earner_target = await resolve_earner_target(
        session,
        tenant_id=tenant_id,
        earner_user_id=agent_user_id,
        destination=outcome.destination,
        currency=currency,
    )
    if outcome.self_amount > 0 and earner_target.account_id is None:
        raise CommissionWalletMissing()
```

Set `ChargeAccounts.agent_account_id=earner_target.account_id or agent_wallet.id`,
`parent_account_id=outcome.parent_account_id`, and on `ChargeAmounts`
`commission=outcome.self_amount`, `parent_commission=outcome.parent_amount`,
`commission_tax=tax.commission_tax`,
`parent_commission_tax=tax.parent_commission_tax`.

Add `CommissionWalletMissing` to `backend/app/shared/exceptions/__init__.py`:

```python
class CommissionWalletMissing(AppHTTPException):
    """A rule pays into a commission wallet the earner does not hold (spec §7.2).

    Unreachable in practice once provisioning (Plan 1 §6) is in place — this is
    a backstop. It fails CLOSED rather than falling back to the main wallet:
    silently paying spendable commission where a review hold was configured is
    the failure mode this whole feature exists to prevent.
    """

    def __init__(self) -> None:
        super().__init__(
            422,
            "commission_wallet_missing",
            "The commission wallet for this earner and currency does not exist.",
        )
```

- [ ] **Step 4: Make `skip_receive_cap` conditional**

Still in cash-in, where `skip_receive_cap=True` is currently passed
unconditionally on the commission path:

```python
        # Only the MAIN wallet has a ceiling to skip. A commission wallet is
        # uncapped by account type (Plan 1, invariant #11 third shape), so the
        # flag would be a no-op there — passing it anyway would wrongly suggest
        # the exemption comes from the flag rather than from the account type.
        skip_receive_cap=outcome.destination == "main_wallet",
```

- [ ] **Step 5: Persist the parent amount**

Pass `parent_commission_amount=assembled.parent_commission_amount` to the
`PostTransactionRequest`, and record `outcome.parent_skip_reason` on the
transaction's metadata payload when it is not None.

- [ ] **Step 6: Run the test to verify it passes**

```bash
pytest tests/cashin/test_cashin_commission_destination.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Run the cash-in suite for regressions**

```bash
pytest tests/cashin -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/cashin/ backend/app/shared/exceptions/__init__.py \
  backend/tests/cashin/
git commit -m "feat(cashin): route commission by destination and pay the parent"
```

---

## Task 8: Wire cash-out and the external partner path

**Files:**
- Modify: `backend/app/modules/cashout/service.py`
- Modify: `backend/app/modules/external/service.py`
- Test: `backend/tests/cashout/test_cashout_commission_destination.py`
- Test: `backend/tests/external/test_external_commission_destination.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/cashout/test_cashout_commission_destination.py`, mirroring
the cash-in test's three cases against the cash-out fixtures already in
`backend/tests/cashout/`:

```python
"""Cash-out honours the commission destination and pays the parent (spec §7).

Every commission-paying path must be covered — no path may keep the old
"credit the agent's float" target (spec B8.2 acceptance criteria).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import ACCOUNT_TYPE_COMMISSION_WALLET, Account, User


async def _commission_wallet(session: AsyncSession, user: User) -> Account:
    return (
        await session.execute(
            select(Account).where(
                Account.user_id == user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_cashout_commission_lands_in_the_commission_wallet(
    db_session: AsyncSession, cashout_fixture
) -> None:
    wallet = await _commission_wallet(db_session, cashout_fixture.agent)
    await cashout_fixture.perform(amount=Decimal("500"))
    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance > Decimal("0")


@pytest.mark.asyncio
async def test_cashout_pays_the_parent(
    db_session: AsyncSession, cashout_fixture
) -> None:
    wallet = await _commission_wallet(db_session, cashout_fixture.super_agent)
    await cashout_fixture.perform(amount=Decimal("500"))
    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance > Decimal("0")
```

Create the equivalent `backend/tests/external/test_external_commission_destination.py`
against the partner-path fixtures in `backend/tests/external/`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/cashout/test_cashout_commission_destination.py \
  tests/external/test_external_commission_destination.py -v
```

Expected: FAIL — commission still credits the agent's main wallet.

- [ ] **Step 3: Apply the same wiring to both services**

Make the identical five changes from Task 7 Steps 3–5 in
`backend/app/modules/cashout/service.py` and
`backend/app/modules/external/service.py`:

1. `calculate_commission` result is an outcome, not a Decimal
2. `calculate_tax` receives `parent_commission=outcome.parent_amount`
3. `resolve_earner_target` picks `agent_account_id`, raising
   `CommissionWalletMissing` when `self_amount > 0` and it is None
4. `ChargeAccounts.parent_account_id` and the two new `ChargeAmounts` fields
5. `skip_receive_cap=outcome.destination == "main_wallet"`, and
   `parent_commission_amount` plus the skip reason on the transaction

`external/service.py` has several commission call sites (`:485`, `:704` and
around). Grep it for `calculate_commission` and update **every** one — a missed
site is a path that silently keeps paying spendable commission:

```bash
grep -n "calculate_commission" backend/app/modules/external/service.py
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/cashout/test_cashout_commission_destination.py \
  tests/external/test_external_commission_destination.py -v
```

Expected: all pass.

- [ ] **Step 5: Confirm no call site was missed**

```bash
grep -rn "calculate_commission" backend/app/ | grep -v "def calculate_commission"
```

Expected: every hit is followed by `.self_amount` / `.parent_amount` usage — no
caller treats the return value as a `Decimal`.

- [ ] **Step 6: Run all money-path suites**

```bash
pytest tests/cashin tests/cashout tests/external tests/payments tests/airtime -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/cashout/ backend/app/modules/external/ \
  backend/tests/cashout/ backend/tests/external/
git commit -m "feat(cashout,external): route commission by destination and pay the parent"
```

---

## Task 9: Admin UI — commission config dialog

**Files:**
- Modify: `admin-ui/app/(authenticated)/pricing/_components/commission-config-dialog.tsx`
- Modify: `admin-ui/app/(authenticated)/pricing/_actions.ts`

Find the real filenames first — the dialog may be named differently:

```bash
grep -rln "commission" admin-ui/app/\(authenticated\)/pricing/
```

- [ ] **Step 1: Add the destination dropdown**

Add a `payout_destination` select with options "Main wallet" and "Commission
wallet". The commission-wallet option is rendered **only** when both hold:

```tsx
// D7: the option is ABSENT, not disabled. A disabled-with-tooltip control
// invites the operator to go looking for a way to enable it; an absent one
// tells them the combination does not exist. The server enforces the same
// rule, so this is convenience, not security.
const commissionWalletSelectable =
  tenant.commission_wallet_enabled &&
  selectedUserType !== null &&
  ["retail", "business"].includes(selectedUserTypeCategory);
```

`selectedUserTypeCategory` comes from the cascading category-then-type picker
already shared across the config dialogs (commit `57bf2b9`) — reuse it rather
than re-fetching the catalog.

- [ ] **Step 2: Add the parent commission fields**

Three inputs — "Parent fixed commission", "Parent variable commission %",
"Parent commission cap (optional)" — in their own labelled section:

```tsx
{/* Required, may be zero (D8). Do NOT default these to 0 in the form state:
    an empty field must fail validation so the operator makes an explicit
    decision about the parent rate rather than shipping an accidental zero. */}
```

Validate that fixed and variable are present and non-negative, and that variable
is `< 1`, before enabling submit.

- [ ] **Step 3: Reset the destination when it becomes unselectable**

When the user changes the type picker to a consumer type or the catch-all while
"Commission wallet" is selected, reset the field to `main_wallet`:

```tsx
// Without this the form would submit a destination the server refuses with
// commission_destination_not_available, and the operator would see a 422 for
// a control that is no longer even on screen.
useEffect(() => {
  if (!commissionWalletSelectable && destination === "commission_wallet") {
    setDestination("main_wallet");
  }
}, [commissionWalletSelectable, destination]);
```

- [ ] **Step 4: Pass the fields through the server action**

Extend the create/replace payload in `_actions.ts` with `payout_destination`,
`parent_fixed_commission`, `parent_variable_commission_pct` and
`parent_commission_cap`. These route through config maker-checker like every
other money config — no new approval path.

- [ ] **Step 5: Verify in the running app**

```bash
cd admin-ui && npm run dev
```

Check by hand: on a flag-on tenant with an agent type selected the commission
wallet option appears; switching to a consumer type removes it and resets the
field; submitting without parent values is blocked; a saved rule round-trips.

- [ ] **Step 6: Commit**

```bash
git add admin-ui/app/\(authenticated\)/pricing/
git commit -m "feat(admin-ui): commission destination and parent rate fields"
```

---

## Task 10: Full verification

- [ ] **Step 1: Run the whole backend suite**

```bash
cd backend && make test
```

Expected: all pass, `tests/invariants/test_ledger_sum_to_zero.py` included — a
three-commission-leg transaction is exactly what that invariant exists to catch.

- [ ] **Step 2: Lint, types, migration drift**

```bash
make check
```

Expected: clean.

- [ ] **Step 3: End-to-end by hand**

```bash
make seed && make dev
```

Perform a cash-in as the seeded agent. Confirm: the agent's commission wallet
balance rises, their main wallet drops by exactly the principal, the super-agent's
commission wallet rises, and the transaction lists `commission_amount` and
`parent_commission_amount`.

- [ ] **Step 4: Commit any seed adjustments**

```bash
git add backend/scripts/seed.py
git commit -m "chore(seed): commission destination and parent rate in seed config"
```

---

## Done when

- A commission rule can name either wallet, and the choice is honoured on cash-in, cash-out and partner paths
- A rule naming the commission wallet cannot be saved where no such wallet can exist
- The earner's parent is paid from the same rule, one level only, fail-open with a recorded reason
- Both legs are taxed independently on the same axis, and every transaction balances
- Commission paid into a commission wallet does not change the earner's spendable balance
- Existing main-wallet rules behave exactly as before
- `make test` and `make check` are green

**Next:** Plan 3 (`2026-08-26-commission-wallets-3-batches.md`) — bulk disbursement and withdrawal, CSV upload, maker-checker, and the read surfaces.
