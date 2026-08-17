# Base & Derived Services — Phase 1 (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the backend for base/derived services — explicit `kind`, derived-only creation, code resolution, and `base_transaction_type` on transactions — so the capability exists and is provably inert until a derived service is created.

**Architecture:** A registry (`app/shared/services_registry.py`) becomes the single source of truth for which service codes the platform implements. `services` gains `kind` + `base_service_code` with paired CHECK constraints so nullness never needs interpreting. One shared resolver (`services/service.resolve_service_code`) turns an optional client-supplied `service_code` into the code that drives permission, pricing, limits and the recorded `transaction_type`; every money flow calls it identically. `transactions` gains a denormalised `base_transaction_type` so clients group by flow without knowing every derived code.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-service-variants-design.md` (rev. 3). Read §3, §4, §6, §7, §12.1 before starting.

**Branch:** `feature/base-derived-services`. Commit to it; **do not push** unless the controller says so.

**Phase scope.** This plan is Phase 1 of the spec's §12.3 rollout — the backend only, which is a no-op for users because no derived service can exist until the admin UI ships. Phases 2 (mobile client fixes) and 3 (admin UI create flow) get their own plans. Do NOT touch `mobile/` or `admin-ui/` in this plan.

**Non-negotiables (from CLAUDE.md):**
- Routers contain no business logic — routers call exactly one service function.
- No DDL outside Alembic. Run `python scripts/check_migrations.py` before committing a model change.
- ORM only, no raw SQL in app code (migrations may use `sa.text` for data backfill).
- Google-style docstrings on every new function/class; comments explain WHY.
- Every new endpoint behaviour needs tests incl. tenant isolation.
- **ONE pytest process at a time** — the test DB is shared. Never run two pytest commands concurrently.
- Never stage `admin-ui/next-env.d.ts` or `test-reports/history.json`.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/app/shared/services_registry.py` (new) | The set of codes the platform implements + which are derivable. No imports from `app.modules` (leaf module, avoids cycles). |
| `backend/tests/shared/test_services_registry.py` (new) | Proves the registry matches the codes the modules actually use — stops it rotting. |
| `backend/alembic/versions/20260818_0056_base_derived_services.py` (new) | `services.kind`, `services.base_service_code`, `transactions.base_transaction_type`, constraints, backfill, dead-config guard. |
| `backend/app/shared/models/services.py` (modify) | The two new columns + CHECK constraints for `create_all` parity. |
| `backend/app/shared/models/transactions.py` (modify) | `base_transaction_type` column. |
| `backend/app/modules/services/schemas.py` (modify) | `kind`/`base_service_code` on `ServiceOut`; `base_service_code` required on create. |
| `backend/app/modules/services/service.py` (modify) | Derived-only create validation, base immutability, base delete refusal, `resolve_service_code`. |
| `backend/app/modules/ledger/service.py` (modify) | Accept + persist `base_transaction_type`. |
| `backend/app/modules/payments/service.py` (modify) | P2P: the reference wiring of `resolve_service_code`. |
| `backend/app/modules/{cashin,cashout,airtime,redemption}/service.py` (modify) | Same wiring, mechanical. |
| `backend/app/modules/identity/schemas.py` (modify) | `base_transaction_type` on `WalletTransactionOut`; `base_service_code` on `MyServiceOut`. |

---

### Task 1: Service registry (TDD)

**Files:**
- Create: `backend/app/shared/services_registry.py`
- Test: `backend/tests/shared/test_services_registry.py`

- [ ] **Step 1: Write the failing test.** Create `backend/tests/shared/test_services_registry.py` (create the `tests/shared/` dir with an empty `__init__.py` if it does not exist):

```python
"""Guards the service-code registry against drift.

The registry is the single source of truth for "the platform implements this
code". If a new money flow ships without registering its code, or a code is
registered with no implementation, these tests fail — otherwise the registry
silently rots and the derived-service validation starts lying.
"""

from app.shared.services_registry import BASE_SERVICE_CODES, DERIVABLE_BASE_CODES


def test_registry_lists_every_implemented_service_code() -> None:
    """Verify the registry matches the nine codes the platform implements"""
    assert BASE_SERVICE_CODES == frozenset(
        {
            "p2p",
            "fund",
            "withdraw",
            "cash_in",
            "cashout",
            "merchant_cashin",
            "airtime_recharge",
            "redemption",
            "change_pin",
        }
    )


def test_change_pin_is_not_derivable() -> None:
    """Verify non-financial flows cannot be derived — nothing to differentiate"""
    assert "change_pin" in BASE_SERVICE_CODES
    assert "change_pin" not in DERIVABLE_BASE_CODES
    assert DERIVABLE_BASE_CODES == BASE_SERVICE_CODES - {"change_pin"}


def test_derivable_codes_are_a_subset_of_base_codes() -> None:
    """Verify every derivable code is a real implemented base"""
    assert DERIVABLE_BASE_CODES <= BASE_SERVICE_CODES
```

- [ ] **Step 2: Run it and watch it fail.**

Run: `cd backend && source .venv/bin/activate && pytest tests/shared/test_services_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.shared.services_registry'`.

- [ ] **Step 3: Implement.** Create `backend/app/shared/services_registry.py`:

```python
"""The service codes the platform implements, and which of them are derivable.

Single source of truth for "does a money flow exist for this code". Before
this module the nine codes were scattered — four as module constants
(`CASH_OUT_SERVICE_CODE` and friends) and five as inline string literals —
so nothing could answer that question programmatically. The derived-service
validation in `modules/services/service.py` depends on it, as does the
migration guard that refuses to run against pre-existing dead config.

Deliberately a leaf module: it imports nothing from `app.modules`, so any
module may import it without risking a cycle.
"""

from __future__ import annotations

# A code belongs here only when a module + endpoint actually implement it.
# Adding a code without an implementation reintroduces the dead-config bug
# this registry exists to prevent (spec §1a).
BASE_SERVICE_CODES: frozenset[str] = frozenset(
    {
        "p2p",
        "fund",
        "withdraw",
        "cash_in",
        "cashout",
        "merchant_cashin",
        "airtime_recharge",
        "redemption",
        "change_pin",
    }
)

# `change_pin` moves no money, so it has no fee or limit to differentiate —
# a derived copy of it would be meaningless (spec §3).
NON_DERIVABLE_BASE_CODES: frozenset[str] = frozenset({"change_pin"})

DERIVABLE_BASE_CODES: frozenset[str] = BASE_SERVICE_CODES - NON_DERIVABLE_BASE_CODES
```

- [ ] **Step 4: Run it and watch it pass.**

Run: `cd backend && source .venv/bin/activate && pytest tests/shared/test_services_registry.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Lint + type check.**

Run: `cd backend && source .venv/bin/activate && ruff check app/shared/services_registry.py tests/shared/ && mypy app/shared/services_registry.py`
Expected: both clean.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/shared/services_registry.py backend/tests/shared/
git commit -m "feat(services): registry of implemented service codes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Migration + model columns

**Files:**
- Create: `backend/alembic/versions/20260818_0056_base_derived_services.py`
- Modify: `backend/app/shared/models/services.py`
- Modify: `backend/app/shared/models/transactions.py`
- Test: `backend/tests/services/test_base_derived_model.py` (new)

Current migration head is `0055`. This migration is `0056`, `down_revision = "0055"`.

- [ ] **Step 1: Write the migration.** Create `backend/alembic/versions/20260818_0056_base_derived_services.py`:

```python
"""base/derived service kinds + denormalised base_transaction_type

Adds `services.kind` ('base' | 'derived') and `services.base_service_code`,
with paired CHECK constraints so the base/derived distinction never has to be
inferred from a NULL (spec §4). Also adds `transactions.base_transaction_type`
so API clients can group by flow without knowing every derived code that will
ever exist (spec §12.1) — denormalised rather than joined so history stays
correct even if a derived service is later deleted.

Backfills every existing services row to kind='base' (they are all platform
flows today) and every transactions row's base_transaction_type to its own
transaction_type (no derived services exist yet, so each IS its own base).

GUARD: refuses to run if any live services row carries a code the platform
does not implement. Such a row is pre-existing dead config, and silently
converting it to a "base service" would make the registry lie. Delete or
rename the offending rows first — the error lists them.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.shared.services_registry import BASE_SERVICE_CODES

revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the kind/base columns, backfill, and constrain."""
    bind = op.get_bind()

    # Guard: dead config must be resolved by a human, not guessed at here.
    codes = ", ".join(f"'{c}'" for c in sorted(BASE_SERVICE_CODES))
    unknown = bind.execute(
        sa.text(
            f"SELECT tenant_id, code FROM services "  # noqa: S608 - codes are a static allow-list
            f"WHERE deleted_at IS NULL AND code NOT IN ({codes})"
        )
    ).fetchall()
    if unknown:
        listed = "; ".join(f"tenant={row[0]} code={row[1]}" for row in unknown)
        raise RuntimeError(
            "Cannot migrate: services rows exist with codes the platform does "
            f"not implement ({listed}). These are dead config — delete them or "
            "rename them to an implemented code, then re-run."
        )

    op.add_column(
        "services",
        sa.Column("kind", sa.String(10), nullable=False, server_default="base"),
    )
    op.add_column("services", sa.Column("base_service_code", sa.String(50), nullable=True))
    op.create_check_constraint(
        "ck_services_kind", "services", "kind IN ('base', 'derived')"
    )
    # The pairing is what makes NULL meaningless rather than meaningful.
    op.create_check_constraint(
        "ck_services_kind_base_pairing",
        "services",
        "(kind = 'base' AND base_service_code IS NULL) "
        "OR (kind = 'derived' AND base_service_code IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_services_base_not_self",
        "services",
        "base_service_code IS NULL OR base_service_code <> code",
    )

    # Every existing transaction is its own base (no derived services yet).
    op.add_column(
        "transactions", sa.Column("base_transaction_type", sa.String(50), nullable=True)
    )
    op.execute(sa.text("UPDATE transactions SET base_transaction_type = transaction_type"))
    op.alter_column(
        "transactions",
        "base_transaction_type",
        existing_type=sa.String(50),
        nullable=False,
    )


def downgrade() -> None:
    """Soft-delete derived services, then drop the columns.

    Derived rows must go first: without `base_service_code` their codes
    resolve to no implementation, so leaving them live would recreate exactly
    the dead-config state the upgrade guard rejects.
    """
    op.execute(
        sa.text("UPDATE services SET deleted_at = now() WHERE kind = 'derived'")
    )
    op.drop_column("transactions", "base_transaction_type")
    op.drop_constraint("ck_services_base_not_self", "services", type_="check")
    op.drop_constraint("ck_services_kind_base_pairing", "services", type_="check")
    op.drop_constraint("ck_services_kind", "services", type_="check")
    op.drop_column("services", "base_service_code")
    op.drop_column("services", "kind")
```

- [ ] **Step 2: Add the model columns.** In `backend/app/shared/models/services.py`, inside `Service.__table_args__` add the three CheckConstraints alongside the existing ones (so `Base.metadata.create_all` gives the test DB the same shape):

```python
        CheckConstraint("kind IN ('base', 'derived')", name="ck_services_kind"),
        CheckConstraint(
            "(kind = 'base' AND base_service_code IS NULL) "
            "OR (kind = 'derived' AND base_service_code IS NOT NULL)",
            name="ck_services_kind_base_pairing",
        ),
        CheckConstraint(
            "base_service_code IS NULL OR base_service_code <> code",
            name="ck_services_base_not_self",
        ),
```

and add the columns to the class body (next to `status`):

```python
    # 'base' = a flow the platform implements (see app/shared/services_registry);
    # 'derived' = operator-created, delegates to a base. Explicit rather than
    # inferred from base_service_code being NULL, because this is the most
    # important fact about a row (spec §3).
    kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default="base")
    # The base's `code`. NOT NULL for kind='derived', NULL for kind='base' —
    # enforced by ck_services_kind_base_pairing. Intentionally not an FK: the
    # base is identified by code, is per-tenant, and is soft-deletable.
    base_service_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

Ensure `CheckConstraint` and `String` are imported in that file (they already are — verify).

- [ ] **Step 3: Add the transactions column.** In `backend/app/shared/models/transactions.py`, next to `transaction_type`:

```python
    # The BASE flow this transaction belongs to. Equals `transaction_type` for
    # transactions on a base service; for a derived service it names the base.
    # Denormalised so clients can group by flow without knowing every derived
    # code, and so history stays correct if a derived service is later deleted
    # (spec §12.1).
    base_transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
```

- [ ] **Step 4: Write the model test.** Create `backend/tests/services/test_base_derived_model.py`:

```python
"""Model-level guards for the base/derived service columns.

The CHECK constraints are the reason `base_service_code IS NULL` never has to
be interpreted — these tests prove the invalid combinations are unrepresentable.
"""

import pytest
from sqlalchemy.exc IntegrityError  # noqa: F401 - placeholder, see step 5
```

STOP — that import line is deliberately wrong so you notice: write the file properly as:

```python
"""Model-level guards for the base/derived service columns.

The CHECK constraints are the reason `base_service_code IS NULL` never has to
be interpreted — these tests prove the invalid combinations are unrepresentable.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Service, Tenant


@pytest.mark.asyncio
async def test_base_service_persists_without_a_base_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a base service is stored with kind='base' and no base code"""
    db_session.add(
        Service(tenant_id=test_tenant.id, code="p2p", display_name="P2P", kind="base")
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_derived_service_requires_a_base_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify kind='derived' without a base code violates the pairing CHECK"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p_diaspora",
                    display_name="Diaspora P2P",
                    kind="derived",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_base_service_rejects_a_base_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify kind='base' carrying a base code violates the pairing CHECK"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p",
                    display_name="P2P",
                    kind="base",
                    base_service_code="cashout",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_service_cannot_be_its_own_base(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a self-referencing base code is rejected"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p",
                    display_name="P2P",
                    kind="derived",
                    base_service_code="p2p",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a kind outside base/derived violates the enum CHECK"""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Service(
                    tenant_id=test_tenant.id,
                    code="p2p",
                    display_name="P2P",
                    kind="variant",
                )
            )
            await db_session.flush()
```

- [ ] **Step 5: Apply the migration and run the tests.**

Run: `cd backend && source .venv/bin/activate && alembic upgrade head && pytest tests/services/test_base_derived_model.py -q`
Expected: migration applies; `5 passed`.

If the migration's guard fires, it means the dev DB has dead-config service rows (a real possibility — the demo DB may contain experiments). Report the listed rows to the controller instead of deleting them yourself.

- [ ] **Step 6: Verify no model/migration drift, then commit.**

Run: `cd backend && source .venv/bin/activate && python ../scripts/check_migrations.py && ruff check app/shared/ alembic/versions/20260818_0056_base_derived_services.py && mypy app/shared/models/`
Expected: "No new upgrade operations detected."; lint and mypy clean.

```bash
git add backend/alembic/versions/20260818_0056_base_derived_services.py backend/app/shared/models/services.py backend/app/shared/models/transactions.py backend/tests/services/test_base_derived_model.py
git commit -m "feat(services): base/derived kind columns + base_transaction_type

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `base_transaction_type` written by the ledger

**Files:**
- Modify: `backend/app/modules/ledger/service.py`
- Test: `backend/tests/ledger/test_base_transaction_type.py` (new)

The column is NOT NULL, so `post_transaction` must set it. Default it to
`transaction_type` so every existing caller keeps working untouched — that is
what makes this task a no-op for the eight flows until Task 5 wires them.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/ledger/test_base_transaction_type.py`:

```python
"""base_transaction_type plumbing through the ledger choke point.

Every transaction records the BASE flow it belongs to so clients can group by
flow without knowing every derived code (spec §12.1). Callers that don't pass
one get their transaction_type, which keeps all pre-existing flows correct.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_base_transaction_type_defaults_to_transaction_type(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a caller that omits the base gets transaction_type recorded"""
    # Build the request with whatever helper tests/ledger/ already uses for a
    # balanced two-leg transaction (grep the sibling test files for the local
    # factory — reuse it rather than hand-rolling accounts here).
    raise AssertionError("replace with the sibling-test factory pattern")


@pytest.mark.asyncio
async def test_base_transaction_type_is_recorded_when_supplied(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify an explicit base is stored alongside a derived transaction_type"""
    raise AssertionError("replace with the sibling-test factory pattern")
```

**Implementer:** the two bodies above are intentionally stubs because the
account/ledger fixtures differ across this repo's test modules. Open
`backend/tests/ledger/` and reuse the existing balanced-transaction helper
from a sibling test file, then write both tests properly:

- test 1: call `post_transaction` with `transaction_type="p2p"` and no base;
  assert the persisted row has `base_transaction_type == "p2p"`.
- test 2: call it with `transaction_type="p2p_diaspora"` and
  `base_transaction_type="p2p"`; assert both columns persist as given.

- [ ] **Step 2: Run and watch fail.**

Run: `cd backend && source .venv/bin/activate && pytest tests/ledger/test_base_transaction_type.py -q`
Expected: FAIL — the request model rejects `base_transaction_type`, or the row lacks the column value.

- [ ] **Step 3: Implement.** In `backend/app/modules/ledger/service.py`:

Add to `PostTransactionRequest` (next to `transaction_type`):

```python
    # The BASE flow for this transaction. Omitted → same as transaction_type,
    # which is correct for every base-service flow; a derived service passes
    # its base so clients can group by flow (spec §12.1).
    base_transaction_type: str | None = None
```

Where the `Transaction(...)` row is constructed in `post_transaction`, set:

```python
        base_transaction_type=request.base_transaction_type or request.transaction_type,
```

Update the `post_transaction` docstring's Args section to document the new field.

- [ ] **Step 4: Run and watch pass.**

Run: `cd backend && source .venv/bin/activate && pytest tests/ledger/test_base_transaction_type.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Prove nothing regressed** (this touches the choke point every money path uses).

Run: `cd backend && source .venv/bin/activate && pytest tests/ledger/ tests/payments/ -q`
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/modules/ledger/service.py backend/tests/ledger/test_base_transaction_type.py
git commit -m "feat(ledger): record base_transaction_type on every transaction

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Derived-only catalog API

**Files:**
- Modify: `backend/app/modules/services/schemas.py`
- Modify: `backend/app/modules/services/service.py`
- Test: `backend/tests/services/test_derived_service_api.py` (new)

Implements spec §6: creation is derived-only, base rows are immutable in
their `base_service_code` and undeletable, and the five documented error
codes are returned.

- [ ] **Step 1: Schemas.** In `backend/app/modules/services/schemas.py`:

Add to `ServiceOut` (after `status`):

```python
    kind: str
    base_service_code: str | None
```

Add to `ServiceCreateRequest` — **required**, because only derived services
can be created here:

```python
    # Required: base services ship with the platform and are provisioned per
    # tenant, so the only thing this endpoint creates is a derived service
    # (spec §6). `kind` is deliberately NOT a client field.
    base_service_code: str = Field(
        min_length=2,
        max_length=50,
        description="Code of the platform base service this derives from.",
    )
```

Do **not** add `base_service_code` to `ServiceUpdateRequest` — immutability is
expressed by its absence, and `extra="forbid"` already turns an attempt into a
422. (§6 also specifies a 409 for an explicit attempt; the forbid-extra 422 is
the stricter, simpler contract — note this deviation in your report so the
controller can accept or reject it.)

- [ ] **Step 2: Write the failing tests.** Create `backend/tests/services/test_derived_service_api.py`. Model the client/auth fixtures on the existing `backend/tests/services/` test files.

```python
"""Derived-service creation via the admin catalog API (spec §6).

Only derived services can be created here: base services ship with the
platform. These tests pin the five rejection paths, because each one is a way
an operator could otherwise create config that silently never works.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Service, Tenant


async def _seed_base(session: AsyncSession, tenant: Tenant, code: str) -> Service:
    """Persist an active base service the way provision_tenant_defaults does."""
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code.replace("_", " ").title(),
        kind="base",
        status="active",
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_admin_can_create_a_derived_service(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a derived service is created against a live base"""
    await _seed_base(db_session, test_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "derived"
    assert body["base_service_code"] == "cashout"


@pytest.mark.asyncio
async def test_create_requires_a_base_service_code(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify omitting the base is refused — base services aren't created here"""
    resp = await async_client.post(
        "/api/v1/services",
        json={
            "tenant_id": str(test_tenant.id),
            "code": "school_fees",
            "display_name": "School Fees",
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_rejects_a_non_derivable_base(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify change_pin cannot be derived — no fee or limit to differentiate"""
    await _seed_base(db_session, test_tenant, "change_pin")

    resp = await async_client.post(
        "/api/v1/services",
        json={
            "tenant_id": str(test_tenant.id),
            "code": "change_pin_fast",
            "display_name": "Fast PIN change",
            "base_service_code": "change_pin",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_base_service"


@pytest.mark.asyncio
async def test_create_rejects_a_base_absent_from_the_tenant(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify deriving from a base this tenant doesn't have is refused"""
    resp = await async_client.post(
        "/api/v1/services",
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_base_service"


@pytest.mark.asyncio
async def test_create_rejects_a_code_that_shadows_a_platform_code(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a derived service cannot take an implemented platform code"""
    await _seed_base(db_session, test_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        json={
            "tenant_id": str(test_tenant.id),
            "code": "p2p",
            "display_name": "Sneaky P2P",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "service_code_reserved"


@pytest.mark.asyncio
async def test_derived_service_is_tenant_isolated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Verify a base in another tenant cannot satisfy this tenant's derive"""
    await _seed_base(db_session, other_tenant, "cashout")

    resp = await async_client.post(
        "/api/v1/services",
        json={
            "tenant_id": str(test_tenant.id),
            "code": "cashout_atm",
            "display_name": "Cash Out (ATM)",
            "base_service_code": "cashout",
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "invalid_base_service"
```

- [ ] **Step 3: Run and watch fail.**

Run: `cd backend && source .venv/bin/activate && pytest tests/services/test_derived_service_api.py -q`
Expected: FAIL — validation not implemented.

- [ ] **Step 4: Implement the validation.** In `backend/app/modules/services/service.py`, add a private validator and call it at the top of `create_service` (before the `Service(...)` construction), and set `kind="derived"` / `base_service_code=payload.base_service_code` on the row.

```python
async def _assert_valid_derived_payload(
    session: AsyncSession, payload: ServiceCreateRequest
) -> None:
    """Reject a derived-service create that could never work.

    Three failure modes, each of which would otherwise produce config that
    silently never executes (spec §6):
      - the named base isn't derivable (non-financial, or not implemented);
      - the base isn't provisioned live in this tenant;
      - the new code shadows a platform code, which would make the derived
        row ambiguous with the base flow itself.

    Args:
        session: Async DB session (read-only here).
        payload: The validated create request.

    Raises:
        AppHTTPException: 422 `invalid_base_service` or `service_code_reserved`.
    """
    if payload.code in BASE_SERVICE_CODES:
        raise AppHTTPException(
            422,
            "service_code_reserved",
            f"'{payload.code}' is a platform service code and cannot be reused.",
        )
    if payload.base_service_code not in DERIVABLE_BASE_CODES:
        raise AppHTTPException(
            422,
            "invalid_base_service",
            f"'{payload.base_service_code}' is not a derivable platform service. "
            f"Derivable: {', '.join(sorted(DERIVABLE_BASE_CODES))}.",
        )
    base = (
        await session.execute(
            select(Service).where(
                Service.tenant_id == payload.tenant_id,
                Service.code == payload.base_service_code,
                Service.kind == "base",
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if base is None:
        raise AppHTTPException(
            422,
            "invalid_base_service",
            f"Base service '{payload.base_service_code}' is not provisioned for "
            "this tenant.",
        )
```

Import `BASE_SERVICE_CODES` and `DERIVABLE_BASE_CODES` from
`app.shared.services_registry`, and `AppHTTPException` from
`app.shared.exceptions` (match how sibling modules import it).

Also guard base rows in the update and delete paths — find `update_service`
and the soft-delete function and add, after the row is loaded:

```python
    if service.kind == "base":
        raise AppHTTPException(
            409,
            "base_service_protected",
            "Base services ship with the platform and cannot be deleted.",
        )
```

(delete path only — `update_service` must still allow status/display_name/
policy edits on a base, per spec §6. Do not add the guard there.)

- [ ] **Step 5: Run and watch pass, then check the whole module.**

Run: `cd backend && source .venv/bin/activate && pytest tests/services/ -q`
Expected: all pass, including the pre-existing service tests.

Note: pre-existing tests that create services without `base_service_code`
will now 422. That is the intended contract change — **update those tests** to
seed a base row and pass `base_service_code`, and say in your report how many
you changed.

- [ ] **Step 6: Lint, type check, commit.**

Run: `cd backend && source .venv/bin/activate && ruff check app/modules/services/ tests/services/ && mypy app/modules/services/`

```bash
git add backend/app/modules/services/ backend/tests/services/
git commit -m "feat(services): derived-only creation with base validation

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `resolve_service_code` + P2P reference wiring

**Files:**
- Modify: `backend/app/modules/services/service.py`
- Modify: `backend/app/modules/payments/service.py`, `backend/app/modules/payments/schemas.py`
- Test: `backend/tests/services/test_resolve_service_code.py` (new), `backend/tests/payments/test_p2p_derived_service.py` (new)

Implements spec §7 (resolution) and §6.2 (narrowing-only intersection). P2P is
the reference wiring; Task 6 replicates it mechanically.

- [ ] **Step 1: Write the resolver tests.** Create `backend/tests/services/test_resolve_service_code.py` covering, with a base + derived row seeded per test (reuse the `_seed_base` shape from Task 4):

- omitted `service_code` → returns the base code unchanged;
- explicit base code → returns it;
- derived code whose base matches → returns the derived code;
- derived code whose base does NOT match the endpoint's base → 422 `service_code_mismatch`;
- unknown code → 404 `service_not_found`;
- disabled derived → 409 `service_disabled`;
- cross-tenant code → 404 `service_not_found`;
- derived policy narrower than base (base allows `[web, mobile]`, derived
  `[web]`) → resolving for channel `mobile` raises the module's existing
  channel-denied error; resolving for `web` succeeds;
- derived policy naming a channel the base excludes → 422
  `policy_wider_than_base` **at save time** (that assertion belongs in Task 4's
  API test file — add it there rather than here).

- [ ] **Step 2: Run and watch fail.**

Run: `cd backend && source .venv/bin/activate && pytest tests/services/test_resolve_service_code.py -q`
Expected: FAIL — `resolve_service_code` does not exist.

- [ ] **Step 3: Implement the resolver** in `backend/app/modules/services/service.py`:

```python
async def resolve_service_code(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    base_code: str,
    requested_code: str | None,
) -> str:
    """Resolve the service code a money flow should transact under.

    Every money endpoint calls this exactly once, before any ledger work, so
    all flows behave identically (spec §7). The returned code drives
    permission, pricing, limits and the recorded `transaction_type`; the
    caller passes `base_code` as `base_transaction_type` regardless.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope.
        base_code: The endpoint's own platform code, e.g. 'p2p'.
        requested_code: The client-supplied `service_code`, or None.

    Returns:
        `base_code` when nothing was requested; otherwise the resolved code.

    Raises:
        AppHTTPException: 404 `service_not_found`, 409 `service_disabled`,
            422 `service_code_mismatch`.
    """
    if requested_code is None or requested_code == base_code:
        return base_code

    row = (
        await session.execute(
            select(Service).where(
                Service.tenant_id == tenant_id,
                Service.code == requested_code,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppHTTPException(404, "service_not_found", "Service not found.")
    if row.status != "active":
        raise AppHTTPException(
            409, "service_disabled", f"Service '{requested_code}' is disabled."
        )
    # A derived service may only be invoked through its own base's endpoint —
    # otherwise a cash-out derivative could be driven by the P2P flow.
    if row.kind != "derived" or row.base_service_code != base_code:
        raise AppHTTPException(
            422,
            "service_code_mismatch",
            f"Service '{requested_code}' cannot be used for '{base_code}'.",
        )
    return requested_code
```

- [ ] **Step 4: Wire P2P.** In `backend/app/modules/payments/schemas.py` add to the P2P request model:

```python
    # Optional derived service to transact under. Omitted → plain 'p2p'
    # (identical to pre-existing behaviour).
    service_code: str | None = Field(default=None, max_length=50)
```

In `p2p_transfer` (`backend/app/modules/payments/service.py`), immediately
after the tenant assertion and BEFORE the permission check, resolve once and
use the resolved code everywhere `"p2p"` is currently passed —
`require_permission`, `check_limits`, `require_pricing_and_limits`,
`resolve_fee`, and the `PostTransactionRequest`:

```python
    from app.modules.services.service import resolve_service_code

    service_code = await resolve_service_code(
        session,
        tenant_id=tenant_id,
        base_code="p2p",
        requested_code=request.service_code,
    )
```

and on the `PostTransactionRequest`: `transaction_type=service_code,
base_transaction_type="p2p"`.

- [ ] **Step 5: Write the P2P integration tests.** Create
`backend/tests/payments/test_p2p_derived_service.py`:

- omitting `service_code` records `transaction_type == "p2p"` and
  `base_transaction_type == "p2p"` (regression: today's behaviour unchanged);
- a derived `p2p_diaspora` with its OWN pricing + limit configs records
  `transaction_type == "p2p_diaspora"`, `base_transaction_type == "p2p"`, and
  charges the derived fee — assert the fee differs from the base's;
- a derived service with **no pricing config** → 422 and **no transaction row
  is created** (query the table to prove it);
- a derived service with no limit config → 422;
- exhausting the derived service's daily count cap does NOT block a plain
  `p2p` transfer (limit independence).

- [ ] **Step 6: Run everything that could regress.**

Run: `cd backend && source .venv/bin/activate && pytest tests/services/ tests/payments/ tests/ledger/ -q`
Expected: all pass.

- [ ] **Step 7: Lint, type check, commit.**

```bash
git add backend/app/modules/services/service.py backend/app/modules/payments/ backend/tests/services/test_resolve_service_code.py backend/tests/payments/test_p2p_derived_service.py
git commit -m "feat(services): resolve_service_code + P2P derived-service support

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Wire the remaining money flows

**Files:**
- Modify: `backend/app/modules/cashin/service.py` + schemas (`cash_in`, `merchant_cashin`)
- Modify: `backend/app/modules/cashout/service.py` + schemas (`cashout`)
- Modify: `backend/app/modules/airtime/service.py` + schemas (`airtime_recharge`)
- Modify: `backend/app/modules/redemption/service.py` + schemas (`redemption`)
- Modify: `backend/app/modules/treasury/service.py` (`fund`, `withdraw`) — these are
  admin/maker-checker flows; add `service_code` only if the request schema
  already reaches an operator form. If threading it would require changing the
  money-operations payload contract, **skip and report** rather than expanding
  scope.
- Test: one test per flow in the matching `backend/tests/<module>/` directory

Mechanically identical to Task 5 step 4 for each flow: add the optional
`service_code` field, resolve once before the permission check, use the
resolved code for permission/pricing/limits/`transaction_type`, and pass the
flow's own code as `base_transaction_type`.

- [ ] **Step 1:** For each flow in turn — add the field, resolve, thread it.
- [ ] **Step 2:** For each flow, add one test asserting the derived code is
  recorded with the correct `base_transaction_type`, and one asserting the
  omitted-`service_code` path is unchanged.
- [ ] **Step 3:** Run the full backend suite — this is the first point where
  every flow has changed.

Run: `cd backend && source .venv/bin/activate && make test`
Expected: everything passes (this takes ~45–75 min; run it once, do not run
concurrent pytest processes).

- [ ] **Step 4: Commit.**

```bash
git add backend/app/modules backend/tests
git commit -m "feat(services): derived-service support across all money flows

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Client-facing read models

**Files:**
- Modify: `backend/app/modules/identity/schemas.py`
- Test: `backend/tests/identity/test_me_services_base_code.py` (new)

Phase 2 (mobile) depends on these two fields existing, so they ship here.

- [ ] **Step 1: Write the failing test.** Create
`backend/tests/identity/test_me_services_base_code.py` asserting that
`GET /api/v1/identity/me/services` returns `base_service_code` for a derived
service (equal to its base) and `null` for a base service — model the auth
fixture on the existing `backend/tests/identity/` tests that call `/me/*`.

- [ ] **Step 2: Run and watch fail.**

Run: `cd backend && source .venv/bin/activate && pytest tests/identity/test_me_services_base_code.py -q`
Expected: FAIL — field absent.

- [ ] **Step 3: Implement.** In `backend/app/modules/identity/schemas.py`:

Add to `MyServiceOut`:

```python
    # NULL for a base service; for a derived one, the base it delegates to —
    # so the app can pick an icon/behaviour by base without knowing every
    # derived code (spec §12.1).
    base_service_code: str | None = None
```

Add to `WalletTransactionOut` (next to `transaction_type`):

```python
    # The base flow, for grouping and filtering. Equals `transaction_type`
    # unless the transaction was made on a derived service (spec §12.1).
    base_transaction_type: str
```

Then find where `WalletTransactionOut` is populated (grep for
`_build_recent_txns_payload` in `app/modules/identity/service.py`) and pass the
column through.

- [ ] **Step 4: Run and watch pass.**

Run: `cd backend && source .venv/bin/activate && pytest tests/identity/ -q`
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/modules/identity/ backend/tests/identity/
git commit -m "feat(identity): expose base service + base transaction type to clients

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Full verification + docs

**Files:**
- Modify: `docs/design/05-technical-architecture.md` (or the services design doc — grep `docs/design/` for the file that documents the services catalog)
- Modify: `docs/BACKLOG.md`

- [ ] **Step 1: Full gates.**

Run: `cd backend && source .venv/bin/activate && make check && make test`
Expected: alembic check + ruff + mypy clean; full suite green.

- [ ] **Step 2: Prove the feature is inert.** Confirm no derived service exists
in the dev DB and the seeded flows still work:

Run: `docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform -t -c "SELECT kind, count(*) FROM services WHERE deleted_at IS NULL GROUP BY kind;"`
Expected: only `base` rows. Report the counts.

- [ ] **Step 3: Document it.** Add a short section to the services design doc
covering: base vs derived, that only derived services are creatable, the
resolution rule, and that pricing/limits are never inherited. Link the spec.

- [ ] **Step 4: Backlog.** Add an Epic B4 entry recording that Phase 1 is done
and Phases 2 (mobile: `transactions.tsx` filter, `activityCategory`,
`transactionTitle`) and 3 (admin UI create flow) are outstanding, with the
spec's §12.3 sequencing noted — a derived service must NOT be created in
production until Phase 2 ships.

- [ ] **Step 5: Commit.**

```bash
git add docs/
git commit -m "docs: base/derived services phase 1 + remaining phases

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review notes (already applied)

- **Spec coverage:** §3 kinds → Task 2; §4 data model + registry → Tasks 1–2;
  §5 new-base path → documented in Task 8 (no code needed until a base ships);
  §6 API → Task 4; §6.1 no-approval → nothing to build (absence of a gate);
  §6.2 narrowing → Task 4 save-time check + Task 5 resolution; §7 resolver →
  Task 5; §8 step-up inheritance → **NOT in this plan**, see gap below; §11
  verification → distributed across tasks + Task 8; §12.1 read models →
  Tasks 3 + 7.
- **Known gap, deliberate:** spec §8 says step-up eligibility should be derived
  from the registry plus each derived service's base. That touches
  `STEP_UP_TRANSACTION_TYPES` and the step-up module, and no derived service
  can exist until Phase 3, so it is deferred to a Phase 1b task. The
  implementer must NOT silently skip it — Task 8 step 4 records it in the
  backlog.
- **Type consistency:** `resolve_service_code(session, *, tenant_id, base_code,
  requested_code) -> str` is used identically in Tasks 5 and 6;
  `base_transaction_type` is the same name in the migration, model, ledger
  request, and both read models.
