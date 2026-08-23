# Configurable User Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators create user types through the admin UI, grouped under three fixed categories with a two-level hierarchy in Retail and Business, governed by maker-checker — replacing the five hardcoded Python constants.

**Architecture:** Two new reference tables (`user_type_categories`, `user_types`) modelled directly on the existing `services` catalog: a `code` string that downstream tables reference with **no foreign key**, plus an active/retired status. The `ck_users_user_type` CHECK constraint is dropped and replaced by service-level validation. `resolve_user_type()` and every money-path config lookup are untouched — they still match on the type string exactly as today.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pytest · Next.js 16 App Router · TypeScript · Vitest + Testing Library

**Spec:** [`docs/superpowers/specs/2026-08-23-configurable-user-types-design.md`](../specs/2026-08-23-configurable-user-types-design.md)

---

## Read before starting

- **`.claude/rules/coding-guidelines.md`** — mandatory file and function docstrings. Google-style for Python, JSDoc for TypeScript. This is not optional in this repo.
- **`app/shared/models/services.py`** — the closest existing precedent. Same shape: tenant-scoped catalog, `code` referenced downstream with no FK, active/disabled status, partial unique index. Follow it.
- **`app/modules/config_requests/apply.py`** — five dispatch tables keyed by `CONFIG_TYPE_*`. Task 8 adds a sixth entry to each.
- Run `make check` (alembic check + ruff + mypy) and `make test` from `backend/` before every commit.

## File structure

| File | Responsibility |
|---|---|
| `backend/app/shared/models/user_types.py` | **Create.** `UserTypeCategory` + `UserTypeDef` ORM models and their status/category constants. Named `UserTypeDef`, not `UserType`, because `UserType` is already a Pydantic Literal alias in `identity/schemas.py:20`. |
| `backend/alembic/versions/20260823_0061_configurable_user_types.py` | **Create.** Two tables, two partial indexes, seed rows, drop `ck_users_user_type`. |
| `backend/app/modules/user_types/service.py` | **Create.** Lookup (`list_user_types`, `get_user_type`), validation (`assert_user_type_valid`), and the four maker-checker entry points. |
| `backend/app/modules/user_types/schemas.py` | **Create.** Pydantic request/response models. |
| `backend/app/modules/user_types/router.py` | **Create.** Read-only endpoints — all writes go through `/config-requests`. |
| `backend/app/shared/models/users.py:52-75` | **Modify.** Keep the five constants (still used as seed identifiers and by tests) but delete `PARENT_TYPE_BY_CHILD` and `MERCHANT_USER_TYPES`, whose behaviour moves onto the type rows. |
| `backend/app/modules/identity/service.py:187-204` | **Modify.** `_assert_valid_parent` reads `parent_type_code` from the type row instead of the hardcoded map. |
| `backend/app/modules/config_requests/{schemas,apply}.py` | **Modify.** Add `user_type` to the `ConfigType` Literal and to all five dispatch tables. |
| `backend/app/modules/external/{schemas,service}.py` | **Modify.** Optional `user_type` + `parent_identifier` on partner onboarding. |
| `admin-ui/lib/api-types.ts` | **Modify.** `UserType` becomes `string`; add `UserTypeOption`. Delete the `USER_TYPES` literal array. |
| `admin-ui/app/(authenticated)/user-types/` | **Create.** `page.tsx`, `_actions.ts`, `_components/`. |
| `admin-ui/components/user-type-select.tsx` | **Create.** The shared cascading category→type picker. |

---

## Task 1: ORM models

**Files:**
- Create: `backend/app/shared/models/user_types.py`
- Modify: `backend/app/shared/models/__init__.py`
- Test: `backend/tests/user_types/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/user_types/__init__.py` (empty) and `backend/tests/user_types/test_models.py`:

```python
"""Structural tests for the user-type catalog models."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, UserTypeCategory, UserTypeDef


@pytest.mark.asyncio
async def test_seeded_categories_and_system_types_exist(db_session: AsyncSession) -> None:
    """Verify the migration seeded three categories and five system types."""
    categories = (
        (await db_session.execute(select(UserTypeCategory).order_by(UserTypeCategory.display_order)))
        .scalars()
        .all()
    )
    assert [c.code for c in categories] == ["consumer", "retail", "business"]
    assert [c.supports_hierarchy for c in categories] == [False, True, True]

    types = (
        (await db_session.execute(select(UserTypeDef).where(UserTypeDef.tenant_id.is_(None))))
        .scalars()
        .all()
    )
    by_code = {t.code: t for t in types}
    assert set(by_code) == {"consumer", "agent", "super_agent", "merchant", "head_merchant"}
    assert by_code["agent"].parent_type_code == "super_agent"
    assert by_code["merchant"].parent_type_code == "head_merchant"
    assert by_code["super_agent"].parent_type_code is None
    assert by_code["merchant"].requires_merchant_profile is True
    assert by_code["consumer"].requires_merchant_profile is False
    assert all(t.is_system for t in types)


@pytest.mark.asyncio
async def test_self_parent_is_rejected_by_check(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a type cannot name itself as its own parent."""
    db_session.add(
        UserTypeDef(
            tenant_id=test_tenant.id,
            code="loop",
            label="Loop",
            category_code="retail",
            parent_type_code="loop",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_tenant_cannot_duplicate_its_own_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify (tenant_id, code) is unique for tenant-scoped types."""
    for _ in range(2):
        db_session.add(
            UserTypeDef(
                tenant_id=test_tenant.id,
                code="distributor",
                label="Distributor",
                category_code="retail",
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/user_types/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'UserTypeCategory' from 'app.shared.models'`

- [ ] **Step 3: Write the models**

Create `backend/app/shared/models/user_types.py`:

```python
"""User-type catalog — categories and types (configurable user types, 2026-08-23).

Replaces the five hardcoded constants in `users.py`. Modelled on the services
catalog: `code` is the persistent identifier that `users.user_type` and every
config table store as a plain string, with NO foreign key. That loose coupling
is deliberate — it keeps the money-path config lookups matching on strings
exactly as before — and it is why types are retired, never deleted (spec §11).

Categories are fixed and system-seeded. Retail and Business carry a two-level
type hierarchy; Consumers is flat. Depth is capped by one rule enforced in the
service: a type named as a parent must itself have a NULL `parent_type_code`.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

USER_TYPE_STATUS_ACTIVE = "active"
USER_TYPE_STATUS_RETIRED = "retired"

CATEGORY_CONSUMER = "consumer"
CATEGORY_RETAIL = "retail"
CATEGORY_BUSINESS = "business"


class UserTypeCategory(Base):
    """A fixed super-group of user types — Consumers, Retail or Business.

    Grouping only: a category organises the admin picker and nothing else. No
    config resolves against a category (spec D1). `supports_hierarchy` is false
    for Consumers, so every type in that category must have a NULL parent.
    """

    __tablename__ = "user_type_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    supports_hierarchy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at = created_at_col()


class UserTypeDef(Base):
    """One user type, either platform-wide (system) or tenant-scoped.

    Named `UserTypeDef` rather than `UserType` because `UserType` is already a
    Pydantic Literal alias in `identity/schemas.py`.

    `tenant_id IS NULL` marks a system type: visible to every tenant and
    immutable. A tenant-created type is visible only to that tenant.

    `parent_type_code` alone expresses the hierarchy tier — NULL means a
    top-level type, set means a child hanging under that parent. There is no
    separate tier column because it would be derivable from this one and
    therefore able to disagree with it.
    """

    __tablename__ = "user_types"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{USER_TYPE_STATUS_ACTIVE}', '{USER_TYPE_STATUS_RETIRED}')",
            name="ck_user_types_status",
        ),
        CheckConstraint(
            "parent_type_code IS NULL OR parent_type_code <> code",
            name="ck_user_types_no_self_parent",
        ),
        Index(
            "uq_user_types_system_code",
            "code",
            unique=True,
            postgresql_where=mapped_column("tenant_id").is_(None),
        ),
        Index(
            "uq_user_types_tenant_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=mapped_column("tenant_id").isnot(None),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # NULL = system type, visible to every tenant.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    category_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("user_type_categories.code"), nullable=False
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=USER_TYPE_STATUS_ACTIVE
    )
    # Replaces the MERCHANT_USER_TYPES tuple — drives merchant-profile and
    # collection-account provisioning (Epic 17).
    requires_merchant_profile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    parent_type_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()
```

> **Note on the partial indexes:** if `postgresql_where=mapped_column(...)` does
> not resolve at import time in this SQLAlchemy version, declare both indexes in
> the migration only (Task 2) and drop the two `Index(...)` entries from
> `__table_args__`. The constraint must exist in the database either way; the
> ORM declaration is a convenience. Verify with `make check`.

Then in `backend/app/shared/models/__init__.py`, add to the imports and to `__all__`:

```python
from app.shared.models.user_types import (
    CATEGORY_BUSINESS,
    CATEGORY_CONSUMER,
    CATEGORY_RETAIL,
    USER_TYPE_STATUS_ACTIVE,
    USER_TYPE_STATUS_RETIRED,
    UserTypeCategory,
    UserTypeDef,
)
```

- [ ] **Step 4: Run test — still fails on seeding**

Run: `cd backend && pytest tests/user_types/test_models.py -v`
Expected: the two IntegrityError tests PASS; `test_seeded_categories_and_system_types_exist` FAILS with an empty list. The migration in Task 2 supplies the seed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/shared/models/user_types.py backend/app/shared/models/__init__.py backend/tests/user_types/
git commit -m "feat(user-types): add UserTypeCategory and UserTypeDef models"
```

---

## Task 2: Migration, seed, and dropping the CHECK

**Files:**
- Create: `backend/alembic/versions/20260823_0061_configurable_user_types.py`
- Test: `backend/tests/user_types/test_models.py` (already written in Task 1)

- [ ] **Step 1: Write the migration**

```python
"""Configurable user types: categories, types, seed, drop users CHECK.

Revision ID: 20260823_0061
Revises: 20260820_0060
Create Date: 2026-08-23

Steps 1-3 are additive and reversible. Step 4 — dropping ck_users_user_type —
is the one-way door: the downgrade recreates the CHECK, which fails if any
non-system type is already in use, so the downgrade aborts loudly instead of
half-applying.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260823_0061"
down_revision = "20260820_0060"
branch_labels = None
depends_on = None

_CATEGORIES = [
    # (code, label, display_order, supports_hierarchy)
    ("consumer", "Consumers", 1, False),
    ("retail", "Retail", 2, True),
    ("business", "Business", 3, True),
]

_TYPES = [
    # (code, label, category_code, requires_merchant_profile, parent_type_code)
    ("consumer", "Consumer", "consumer", False, None),
    ("super_agent", "Super agent", "retail", False, None),
    ("agent", "Agent", "retail", False, "super_agent"),
    ("head_merchant", "Head merchant", "business", True, None),
    ("merchant", "Merchant", "business", True, "head_merchant"),
]


def upgrade() -> None:
    """Create the catalog tables, seed them, and drop the users CHECK."""
    op.create_table(
        "user_type_categories",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supports_hierarchy", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    op.create_table(
        "user_types",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("category_code", sa.String(30),
                  sa.ForeignKey("user_type_categories.code"), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("requires_merchant_profile", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("parent_type_code", sa.String(30), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_user_types_status"),
        sa.CheckConstraint("parent_type_code IS NULL OR parent_type_code <> code",
                           name="ck_user_types_no_self_parent"),
    )
    op.create_index("ix_user_types_tenant", "user_types", ["tenant_id"])
    # Two partial indexes, not one composite: a system code must be globally
    # unique, which a composite on (tenant_id, code) cannot express when
    # tenant_id is NULL.
    op.create_index("uq_user_types_system_code", "user_types", ["code"], unique=True,
                    postgresql_where=sa.text("tenant_id IS NULL"))
    op.create_index("uq_user_types_tenant_code", "user_types", ["tenant_id", "code"], unique=True,
                    postgresql_where=sa.text("tenant_id IS NOT NULL"))

    categories = sa.table(
        "user_type_categories",
        sa.column("code", sa.String), sa.column("label", sa.String),
        sa.column("display_order", sa.Integer), sa.column("supports_hierarchy", sa.Boolean),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(categories, [
        {"code": c, "label": lbl, "display_order": o, "supports_hierarchy": h, "is_system": True}
        for c, lbl, o, h in _CATEGORIES
    ])

    types = sa.table(
        "user_types",
        sa.column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String), sa.column("label", sa.String),
        sa.column("category_code", sa.String), sa.column("is_system", sa.Boolean),
        sa.column("status", sa.String),
        sa.column("requires_merchant_profile", sa.Boolean),
        sa.column("parent_type_code", sa.String),
    )
    op.bulk_insert(types, [
        {"tenant_id": None, "code": c, "label": lbl, "category_code": cat,
         "is_system": True, "status": "active",
         "requires_merchant_profile": mp, "parent_type_code": parent}
        for c, lbl, cat, mp, parent in _TYPES
    ])

    # The one-way door. Dynamic types cannot live behind a static allowlist.
    op.drop_constraint("ck_users_user_type", "users", type_="check")


def downgrade() -> None:
    """Recreate the CHECK and drop the catalog — aborts if custom types exist."""
    conn = op.get_bind()
    custom = conn.execute(
        sa.text("SELECT count(*) FROM user_types WHERE is_system = false")
    ).scalar_one()
    if custom:
        raise RuntimeError(
            f"Cannot downgrade: {custom} custom user type(s) exist. "
            "Reassign their users and delete the rows first."
        )
    op.create_check_constraint(
        "ck_users_user_type",
        "users",
        "user_type IN ('consumer', 'agent', 'super_agent', 'merchant', 'head_merchant')",
    )
    op.drop_index("uq_user_types_tenant_code", table_name="user_types")
    op.drop_index("uq_user_types_system_code", table_name="user_types")
    op.drop_index("ix_user_types_tenant", table_name="user_types")
    op.drop_table("user_types")
    op.drop_table("user_type_categories")
```

- [ ] **Step 2: Apply and verify the schema matches the models**

Run: `cd backend && alembic upgrade head && python ../scripts/check_migrations.py`
Expected: upgrade succeeds; the check reports no drift between models and schema.

- [ ] **Step 3: Run the Task 1 tests**

Run: `cd backend && pytest tests/user_types/test_models.py -v`
Expected: all three PASS.

- [ ] **Step 4: Verify the downgrade guard**

Run: `cd backend && alembic downgrade -1 && alembic upgrade head`
Expected: both succeed (no custom types exist yet).

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260823_0061_configurable_user_types.py
git commit -m "feat(user-types): migration, seed three categories and five system types"
```

---

## Task 3: Lookup service

**Files:**
- Create: `backend/app/modules/user_types/__init__.py` (empty), `backend/app/modules/user_types/service.py`
- Test: `backend/tests/user_types/test_lookup.py`

- [ ] **Step 1: Write the failing test**

```python
"""Lookup and visibility tests for the user-type catalog."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import get_user_type, list_user_types
from app.shared.models import Tenant, UserTypeDef


async def _add(session: AsyncSession, tenant: Tenant | None, code: str, **kw) -> UserTypeDef:
    """Insert one type row for a test."""
    row = UserTypeDef(
        tenant_id=tenant.id if tenant else None,
        code=code,
        label=kw.pop("label", code.title()),
        category_code=kw.pop("category_code", "retail"),
        **kw,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_list_returns_system_types_plus_own(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify a tenant sees system types and its own, never another tenant's."""
    await _add(db_session, test_tenant, "distributor")
    await _add(db_session, other_tenant, "franchisee")

    codes = {t.code for t in await list_user_types(db_session, test_tenant.id)}
    assert "consumer" in codes and "agent" in codes  # system
    assert "distributor" in codes                     # own
    assert "franchisee" not in codes                  # other tenant's


@pytest.mark.asyncio
async def test_retired_types_are_hidden_unless_requested(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify retired types leave the picker but remain resolvable."""
    await _add(db_session, test_tenant, "legacy", status="retired")

    active = {t.code for t in await list_user_types(db_session, test_tenant.id)}
    assert "legacy" not in active

    everything = {
        t.code for t in await list_user_types(db_session, test_tenant.id, include_retired=True)
    }
    assert "legacy" in everything

    assert (await get_user_type(db_session, test_tenant.id, "legacy")) is not None


@pytest.mark.asyncio
async def test_get_user_type_is_tenant_isolated(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify one tenant cannot resolve another tenant's custom type."""
    await _add(db_session, other_tenant, "franchisee")
    assert (await get_user_type(db_session, test_tenant.id, "franchisee")) is None
    assert (await get_user_type(db_session, other_tenant.id, "franchisee")) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/user_types/test_lookup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.user_types'`

- [ ] **Step 3: Write the lookup service**

Create `backend/app/modules/user_types/__init__.py` (empty) and `backend/app/modules/user_types/service.py`:

```python
"""User-type catalog service — lookup, visibility and validation.

A tenant's visible types are the platform-wide system types (tenant_id IS NULL)
plus its own. Retired types are excluded from pickers but stay resolvable, so an
existing user or config row referencing one never falls through to the
`user_type IS NULL` default (spec §11).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import USER_TYPE_STATUS_ACTIVE, UserTypeDef


async def list_user_types(
    session: AsyncSession, tenant_id: UUID, *, include_retired: bool = False
) -> list[UserTypeDef]:
    """Return every user type visible to a tenant.

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant.
        include_retired: When True, retired types are included. Use this when
            rendering an existing config row so a retired type still shows its
            label rather than a raw code.

    Returns:
        System types plus the tenant's own, ordered by category then label.
    """
    stmt = select(UserTypeDef).where(
        or_(UserTypeDef.tenant_id.is_(None), UserTypeDef.tenant_id == tenant_id)
    )
    if not include_retired:
        stmt = stmt.where(UserTypeDef.status == USER_TYPE_STATUS_ACTIVE)
    stmt = stmt.order_by(UserTypeDef.category_code, UserTypeDef.label)
    return list((await session.execute(stmt)).scalars().all())


async def get_user_type(
    session: AsyncSession, tenant_id: UUID, code: str
) -> UserTypeDef | None:
    """Resolve one type code for a tenant, retired included, or None.

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant — another tenant's custom type never resolves.
        code: The type code as stored on `users.user_type` / config rows.

    Returns:
        The matching row, preferring the tenant's own over a system type of the
        same code, or None when the code is not visible to this tenant.
    """
    stmt = (
        select(UserTypeDef)
        .where(
            UserTypeDef.code == code,
            or_(UserTypeDef.tenant_id.is_(None), UserTypeDef.tenant_id == tenant_id),
        )
        # A tenant row sorts before the system row (NULLs last), so a tenant
        # override wins if one somehow exists.
        .order_by(UserTypeDef.tenant_id.is_(None))
    )
    return (await session.execute(stmt)).scalars().first()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/user_types/test_lookup.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/user_types/ backend/tests/user_types/test_lookup.py
git commit -m "feat(user-types): tenant-scoped lookup with retired-type visibility"
```

---

## Task 4: Hierarchy and code-collision validation

**Files:**
- Modify: `backend/app/modules/user_types/service.py`
- Modify: `backend/app/shared/exceptions/__init__.py`
- Test: `backend/tests/user_types/test_validation.py`

- [ ] **Step 1: Write the failing test**

```python
"""Validation tests for the four hierarchy rules and code collisions (spec §5)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import assert_type_definition_valid
from app.shared.exceptions import AppHTTPException
from app.shared.models import Tenant, UserTypeDef


async def _add(session: AsyncSession, tenant: Tenant, code: str, **kw) -> UserTypeDef:
    """Insert one tenant-scoped type row for a test."""
    row = UserTypeDef(
        tenant_id=tenant.id, code=code, label=code.title(),
        category_code=kw.pop("category_code", "retail"), **kw,
    )
    session.add(row)
    await session.flush()
    return row


async def _err(session, tenant, **kw) -> str:
    """Call the validator and return the error_code it raises."""
    with pytest.raises(AppHTTPException) as exc:
        await assert_type_definition_valid(session, tenant_id=tenant.id, **kw)
    return exc.value.error_code


@pytest.mark.asyncio
async def test_valid_child_under_toplevel_parent_passes(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a child under an active same-category top-level parent is accepted."""
    await assert_type_definition_valid(
        db_session, tenant_id=test_tenant.id, code="junior_agent",
        category_code="retail", parent_type_code="super_agent",
    )


@pytest.mark.asyncio
async def test_parent_must_be_toplevel(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify the two-level cap: a child cannot hang under another child."""
    assert await _err(
        db_session, test_tenant, code="sub_agent",
        category_code="retail", parent_type_code="agent",   # agent is itself a child
    ) == "parent_type_not_toplevel"


@pytest.mark.asyncio
async def test_parent_must_share_category(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a Retail child cannot hang under a Business parent."""
    assert await _err(
        db_session, test_tenant, code="odd", category_code="retail",
        parent_type_code="head_merchant",
    ) == "parent_type_wrong_category"


@pytest.mark.asyncio
async def test_flat_category_rejects_a_parent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify Consumers stays flat."""
    assert await _err(
        db_session, test_tenant, code="vip", category_code="consumer",
        parent_type_code="consumer",
    ) == "category_does_not_support_hierarchy"


@pytest.mark.asyncio
async def test_unknown_parent_is_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a parent that does not resolve for this tenant is refused."""
    assert await _err(
        db_session, test_tenant, code="x", category_code="retail",
        parent_type_code="does_not_exist",
    ) == "parent_type_not_found"


@pytest.mark.asyncio
async def test_retired_parent_is_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a new child cannot be attached to a retired parent."""
    await _add(db_session, test_tenant, "old_boss", status="retired")
    assert await _err(
        db_session, test_tenant, code="y", category_code="retail",
        parent_type_code="old_boss",
    ) == "parent_type_not_found"


@pytest.mark.asyncio
async def test_system_code_is_reserved(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a tenant cannot shadow a system type code."""
    assert await _err(
        db_session, test_tenant, code="agent", category_code="retail",
    ) == "user_type_code_reserved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/user_types/test_validation.py -v`
Expected: FAIL — `ImportError: cannot import name 'assert_type_definition_valid'`

- [ ] **Step 3: Add the exceptions**

Append to `backend/app/shared/exceptions/__init__.py`, following the existing `AppHTTPException` subclass style in that file:

```python
class UserTypeCodeReserved(AppHTTPException):
    """409 — the code is taken by a platform-wide system type."""

    def __init__(self) -> None:
        super().__init__(409, "user_type_code_reserved",
                         "That code is reserved by a system user type.")


class ParentTypeNotFound(AppHTTPException):
    """422 — the named parent type does not resolve, or is retired."""

    def __init__(self) -> None:
        super().__init__(422, "parent_type_not_found",
                         "The parent user type was not found or is retired.")


class ParentTypeWrongCategory(AppHTTPException):
    """422 — the parent sits in a different category from the child."""

    def __init__(self) -> None:
        super().__init__(422, "parent_type_wrong_category",
                         "The parent user type must be in the same category.")


class ParentTypeNotTopLevel(AppHTTPException):
    """422 — the named parent is itself a child. Caps the hierarchy at two levels."""

    def __init__(self) -> None:
        super().__init__(422, "parent_type_not_toplevel",
                         "The parent user type must itself be a top-level type.")


class CategoryDoesNotSupportHierarchy(AppHTTPException):
    """422 — a parent was supplied for a type in a flat category."""

    def __init__(self) -> None:
        super().__init__(422, "category_does_not_support_hierarchy",
                         "This category does not support a type hierarchy.")


class UserTypeHasActiveChildren(AppHTTPException):
    """409 — a parent type with active children cannot be retired."""

    def __init__(self, children: list[str]) -> None:
        super().__init__(409, "user_type_has_active_children",
                         f"Retire these child types first: {', '.join(children)}.")


class UnknownUserType(AppHTTPException):
    """422 — a user or config references a type that does not resolve."""

    def __init__(self) -> None:
        super().__init__(422, "unknown_user_type",
                         "That user type is not available for this tenant.")
```

- [ ] **Step 4: Write the validator**

Append to `backend/app/modules/user_types/service.py`:

```python
async def assert_type_definition_valid(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    code: str,
    category_code: str,
    parent_type_code: str | None = None,
) -> None:
    """Enforce the code-collision and four hierarchy rules from spec §5.

    Args:
        session: Async DB session.
        tenant_id: The tenant proposing the type.
        code: The proposed code.
        category_code: The category the type sits in.
        parent_type_code: The parent type, or None for a top-level type.

    Raises:
        UserTypeCodeReserved: the code belongs to a system type.
        CategoryDoesNotSupportHierarchy: a parent was given for a flat category.
        ParentTypeNotFound: the parent does not resolve, or is retired.
        ParentTypeWrongCategory: the parent is in a different category.
        ParentTypeNotTopLevel: the parent is itself a child (two-level cap).
    """
    system = (
        await session.execute(
            select(UserTypeDef).where(
                UserTypeDef.code == code, UserTypeDef.tenant_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if system is not None:
        raise UserTypeCodeReserved()

    category = (
        await session.execute(
            select(UserTypeCategory).where(UserTypeCategory.code == category_code)
        )
    ).scalar_one_or_none()
    if category is None:
        raise UnknownUserType()

    if parent_type_code is None:
        return

    if not category.supports_hierarchy:
        raise CategoryDoesNotSupportHierarchy()

    parent = await get_user_type(session, tenant_id, parent_type_code)
    if parent is None or parent.status != USER_TYPE_STATUS_ACTIVE:
        raise ParentTypeNotFound()
    if parent.category_code != category_code:
        raise ParentTypeWrongCategory()
    # THE two-level guarantee: a parent must itself be top-level. No depth
    # counter, no recursion — this single check caps the tree.
    if parent.parent_type_code is not None:
        raise ParentTypeNotTopLevel()
```

Extend the module imports to include `UserTypeCategory` and the new exceptions.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/user_types/test_validation.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/user_types/service.py backend/app/shared/exceptions/__init__.py backend/tests/user_types/test_validation.py
git commit -m "feat(user-types): hierarchy validation with two-level depth cap"
```

---

## Task 5: Create, update and the retire guard

**Files:**
- Create: `backend/app/modules/user_types/schemas.py`
- Modify: `backend/app/modules/user_types/service.py`
- Test: `backend/tests/user_types/test_mutations.py`

- [ ] **Step 1: Write the failing test**

```python
"""Mutation tests — create, relabel, retire, and the active-children guard."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type, replace_user_type_for_scope
from app.shared.exceptions import AppHTTPException
from app.shared.models import USER_TYPE_STATUS_RETIRED, Tenant


def _req(tenant: Tenant, code: str, **kw) -> UserTypeCreateRequest:
    """Build a create request with sensible defaults."""
    return UserTypeCreateRequest(
        tenant_id=tenant.id, code=code, label=kw.pop("label", code.title()),
        category_code=kw.pop("category_code", "retail"), **kw,
    )


@pytest.mark.asyncio
async def test_create_then_relabel(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a type is created, then relabelled in place with its code intact."""
    created = await create_user_type(db_session, _req(test_tenant, "distributor"))
    assert created.code == "distributor" and created.is_system is False
    original_id = created.id

    await replace_user_type_for_scope(
        db_session, [_req(test_tenant, "distributor", label="Master Distributor")]
    )
    await db_session.refresh(created)
    assert created.label == "Master Distributor"
    assert created.code == "distributor"   # code is immutable
    # The row must be updated IN PLACE — a delete+insert would mint a new id and
    # lose created_at for a record downstream tables reference by code (spec D3).
    assert created.id == original_id


@pytest.mark.asyncio
async def test_retire_is_blocked_by_active_children(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a parent with active children cannot be retired."""
    await create_user_type(db_session, _req(test_tenant, "distributor"))
    await create_user_type(
        db_session, _req(test_tenant, "sub_distributor", parent_type_code="distributor")
    )

    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session,
            [_req(test_tenant, "distributor", status=USER_TYPE_STATUS_RETIRED)],
        )
    assert exc.value.error_code == "user_type_has_active_children"


@pytest.mark.asyncio
async def test_retire_succeeds_once_children_are_retired(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the guard lifts after the children are retired."""
    await create_user_type(db_session, _req(test_tenant, "distributor"))
    await create_user_type(
        db_session, _req(test_tenant, "sub_distributor", parent_type_code="distributor")
    )
    await replace_user_type_for_scope(
        db_session,
        [_req(test_tenant, "sub_distributor", parent_type_code="distributor",
              status=USER_TYPE_STATUS_RETIRED)],
    )
    await replace_user_type_for_scope(
        db_session, [_req(test_tenant, "distributor", status=USER_TYPE_STATUS_RETIRED)]
    )


@pytest.mark.asyncio
async def test_system_type_cannot_be_modified(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify system types are immutable."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session, [_req(test_tenant, "agent", label="Renamed")]
        )
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/user_types/test_mutations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.user_types.schemas'`

- [ ] **Step 3: Write the schemas**

Create `backend/app/modules/user_types/schemas.py`:

```python
"""Pydantic v2 schemas for the user-type catalog.

`UserTypeCreateRequest` doubles as the maker-checker payload schema for BOTH
create and update — the config-request pipeline validates every payload against
the type's create schema (`config_requests/apply.py:build_create_schema`), and
an update is expressed as the full desired row.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.models import USER_TYPE_STATUS_ACTIVE


class UserTypeCreateRequest(BaseModel):
    """A proposed user type — the maker-checker payload for create and update."""

    tenant_id: UUID
    code: str = Field(min_length=2, max_length=30, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=60)
    category_code: str = Field(min_length=1, max_length=30)
    requires_merchant_profile: bool = False
    parent_type_code: str | None = Field(default=None, max_length=30)
    status: str = USER_TYPE_STATUS_ACTIVE


class UserTypeOut(BaseModel):
    """A user type as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    code: str
    label: str
    category_code: str
    is_system: bool
    status: str
    requires_merchant_profile: bool
    parent_type_code: str | None
    created_at: datetime


class UserTypeCategoryOut(BaseModel):
    """A category as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    display_order: int
    supports_hierarchy: bool
```

- [ ] **Step 4: Write the mutations**

Append to `backend/app/modules/user_types/service.py`:

```python
async def create_user_type(
    session: AsyncSession,
    request: UserTypeCreateRequest,
    *,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> UserTypeDef:
    """Create a tenant-scoped user type after validating it (spec §5).

    Signature matches `_CreateFn` in `config_requests/apply.py` so this is
    callable directly from the maker-checker dispatch table.

    Raises:
        UserTypeCodeReserved, ParentTypeNotFound, ParentTypeWrongCategory,
        ParentTypeNotTopLevel, CategoryDoesNotSupportHierarchy: see §5.

    Side effects:
        Inserts a `user_types` row and one `user_type.created` audit row.
        Does NOT commit — the config-request pipeline owns the transaction.
    """
    await assert_type_definition_valid(
        session,
        tenant_id=request.tenant_id,
        code=request.code,
        category_code=request.category_code,
        parent_type_code=request.parent_type_code,
    )
    row = UserTypeDef(
        tenant_id=request.tenant_id,
        code=request.code,
        label=request.label,
        category_code=request.category_code,
        is_system=False,
        status=request.status,
        requires_merchant_profile=request.requires_merchant_profile,
        parent_type_code=request.parent_type_code,
    )
    session.add(row)
    await session.flush()
    if admin is not None:
        record_audit_for_admin(
            session, admin,
            tenant_id=request.tenant_id,
            action="user_type.created",
            entity_type="user_type",
            entity_id=str(row.id),
            after_state={"code": row.code, "label": row.label,
                         "category_code": row.category_code,
                         "parent_type_code": row.parent_type_code},
            ip_address=ip_address,
        )
    return row


async def replace_user_type_for_scope(
    session: AsyncSession,
    requests: list[UserTypeCreateRequest],
    *,
    target_config_id: UUID | None = None,
    admin: AdminPrincipal | None = None,
    ip_address: str | None = None,
) -> None:
    """Update a user type IN PLACE. Scope = (tenant_id, code).

    Signature matches `_ReplaceFn` in `config_requests/apply.py`.

    Unlike every other config type, this does NOT delete-and-reinsert. Spec D3
    forbids deleting a user type, and a delete+insert would churn the row id and
    lose `created_at` for a record that downstream tables reference by code. Only
    `label`, `status`, `requires_merchant_profile` and `parent_type_code` are
    mutable; `code` is the join key and never changes.

    Raises:
        AppHTTPException 403: the target is a system type.
        AppHTTPException 404: no such type for this tenant.
        UserTypeHasActiveChildren: retiring a parent that still has active children.
    """
    first = requests[0]
    row = (
        await session.execute(
            select(UserTypeDef).where(
                UserTypeDef.tenant_id == first.tenant_id, UserTypeDef.code == first.code
            )
        )
    ).scalar_one_or_none()
    if row is None:
        # A system type has tenant_id IS NULL, so the tenant-scoped lookup above
        # misses it; distinguish "system, immutable" from "does not exist".
        if await get_user_type(session, first.tenant_id, first.code) is not None:
            raise AppHTTPException(403, "user_type_is_system",
                                   "System user types cannot be modified.")
        raise AppHTTPException(404, "user_type_not_found", "No such user type.")

    before = {"label": row.label, "status": row.status,
              "parent_type_code": row.parent_type_code}

    if first.status == USER_TYPE_STATUS_RETIRED and row.status != USER_TYPE_STATUS_RETIRED:
        children = (
            (await session.execute(
                select(UserTypeDef.code).where(
                    UserTypeDef.parent_type_code == row.code,
                    UserTypeDef.status == USER_TYPE_STATUS_ACTIVE,
                    or_(UserTypeDef.tenant_id.is_(None),
                        UserTypeDef.tenant_id == first.tenant_id),
                )
            )).scalars().all()
        )
        if children:
            raise UserTypeHasActiveChildren(list(children))

    if first.parent_type_code != row.parent_type_code:
        await assert_type_definition_valid(
            session, tenant_id=first.tenant_id, code=f"{first.code}__probe",
            category_code=first.category_code, parent_type_code=first.parent_type_code,
        )

    row.label = first.label
    row.status = first.status
    row.requires_merchant_profile = first.requires_merchant_profile
    row.parent_type_code = first.parent_type_code
    await session.flush()

    if admin is not None:
        record_audit_for_admin(
            session, admin,
            tenant_id=first.tenant_id,
            action="user_type.updated",
            entity_type="user_type",
            entity_id=str(row.id),
            before_state=before,
            after_state={"label": row.label, "status": row.status,
                         "parent_type_code": row.parent_type_code},
            ip_address=ip_address,
        )
```

> **Why the `__probe` code in the re-parent check:** `assert_type_definition_valid`
> also runs the system-code-collision rule, which would trip on the row's own
> code. Passing a code that cannot collide isolates the hierarchy rules. If that
> reads as a hack to the implementing engineer, split the validator into
> `_assert_code_available` and `_assert_hierarchy_valid` and call only the second
> here — that is the cleaner shape and is a welcome refactor.

Add the required imports to the module: `AdminPrincipal`, `record_audit_for_admin`,
`AppHTTPException`, `UserTypeHasActiveChildren`, `USER_TYPE_STATUS_RETIRED`,
`UserTypeCreateRequest`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/user_types/test_mutations.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/user_types/ backend/tests/user_types/test_mutations.py
git commit -m "feat(user-types): in-place update with active-children retire guard"
```

---

## Task 6: Read-only router

**Files:**
- Create: `backend/app/modules/user_types/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/user_types/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
"""API tests for the user-type read endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, UserTypeDef


@pytest.mark.asyncio
async def test_list_requires_admin_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify the endpoint is admin-gated."""
    response = await async_client.get(f"/api/v1/user-types?tenant_id={test_tenant.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_returns_categories_and_types(
    async_client: AsyncClient, db_session: AsyncSession,
    test_tenant: Tenant, other_tenant: Tenant, admin_auth_header: dict[str, str],
) -> None:
    """Verify the payload carries both categories and the tenant's visible types."""
    db_session.add(UserTypeDef(tenant_id=other_tenant.id, code="franchisee",
                               label="Franchisee", category_code="retail"))
    await db_session.commit()

    response = await async_client.get(
        f"/api/v1/user-types?tenant_id={test_tenant.id}", headers=admin_auth_header
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["code"] for c in body["categories"]] == ["consumer", "retail", "business"]
    codes = {t["code"] for t in body["types"]}
    assert "agent" in codes
    assert "franchisee" not in codes    # tenant isolation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/user_types/test_router.py -v`
Expected: FAIL — 404, the route is not registered.

- [ ] **Step 3: Write the router**

Create `backend/app/modules/user_types/router.py`:

```python
"""User-type catalog FastAPI router — read-only, admin-gated.

There are no write endpoints here by design. Every mutation is a maker-checker
proposal through `POST /api/v1/config-requests` with `config_type="user_type"`
(spec D4), so a direct write path would be a governance bypass.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.user_types.schemas import UserTypeCategoryOut, UserTypeOut
from app.modules.user_types.service import list_user_types
from app.shared.models import UserTypeCategory

router = APIRouter(prefix="/api/v1/user-types", tags=["user-types"])


class UserTypeCatalogOut(BaseModel):
    """Categories plus the types visible to one tenant, in one round trip."""

    categories: list[UserTypeCategoryOut]
    types: list[UserTypeOut]


@router.get("", response_model=UserTypeCatalogOut)
async def get_catalog(
    tenant_id: UUID,
    include_retired: bool = False,
    admin: AdminPrincipal = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
) -> UserTypeCatalogOut:
    """Return the categories and every user type visible to `tenant_id`.

    The cascading category→type picker needs both halves together, so this is
    one endpoint rather than two.

    Args:
        tenant_id: The tenant whose custom types are included alongside system ones.
        include_retired: Include retired types — used when rendering an existing
            config row so a retired type still shows its label.
    """
    _ = admin
    categories = (
        (await session.execute(
            select(UserTypeCategory).order_by(UserTypeCategory.display_order)
        )).scalars().all()
    )
    types = await list_user_types(session, tenant_id, include_retired=include_retired)
    return UserTypeCatalogOut(
        categories=[UserTypeCategoryOut.model_validate(c) for c in categories],
        types=[UserTypeOut.model_validate(t) for t in types],
    )
```

In `backend/app/main.py`, import `from app.modules.user_types import router as user_types_router` alongside the other module imports, and add `app.include_router(user_types_router)` next to the other config routers.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/user_types/test_router.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/user_types/router.py backend/app/main.py backend/tests/user_types/test_router.py
git commit -m "feat(user-types): read-only catalog endpoint"
```

---

## Task 7: Wire user_type into maker-checker

**Files:**
- Modify: `backend/app/modules/config_requests/schemas.py:11-19`
- Modify: `backend/app/modules/config_requests/apply.py`
- Modify: `backend/app/shared/models/config_requests.py` (the `CONFIG_TYPE_*` constants)
- Test: `backend/tests/config_requests/test_user_type_requests.py`

- [ ] **Step 1: Write the failing test**

```python
"""Maker-checker tests for the user_type config type."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, UserTypeDef


@pytest.mark.asyncio
async def test_propose_and_approve_creates_the_type(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant,
    make_admin_token, admin_auth_header: dict[str, str],
) -> None:
    """Verify a proposed type only exists after a distinct admin approves it."""
    payload = {
        "config_type": "user_type",
        "operation": "create",
        "payload": {
            "tenant_id": str(test_tenant.id),
            "code": "distributor",
            "label": "Distributor",
            "category_code": "retail",
        },
    }
    proposed = await async_client.post(
        "/api/v1/config-requests", json=payload, headers=admin_auth_header
    )
    assert proposed.status_code == 201, proposed.text
    request_id = proposed.json()["id"]

    # Not applied yet.
    assert (await db_session.execute(
        select(UserTypeDef).where(UserTypeDef.code == "distributor")
    )).scalar_one_or_none() is None

    checker = {"Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub='checker-1')}"}
    approved = await async_client.post(
        f"/api/v1/config-requests/{request_id}/approve", headers=checker
    )
    assert approved.status_code == 200, approved.text

    row = (await db_session.execute(
        select(UserTypeDef).where(UserTypeDef.code == "distributor")
    )).scalar_one()
    assert row.label == "Distributor" and row.is_system is False


@pytest.mark.asyncio
async def test_delete_operation_is_refused(
    async_client: AsyncClient, test_tenant: Tenant, admin_auth_header: dict[str, str]
) -> None:
    """Verify user types can never be deleted, only retired (spec D3)."""
    response = await async_client.post(
        "/api/v1/config-requests",
        json={"config_type": "user_type", "operation": "delete",
              "target_config_id": "00000000-0000-0000-0000-000000000001"},
        headers=admin_auth_header,
    )
    assert response.status_code in (400, 422)
    assert "delete" in response.text.lower() or "retire" in response.text.lower()
```

> If `make_admin_token` does not accept a `sub=` kwarg, read
> `backend/tests/conftest.py:576-620` and use whatever parameter distinguishes
> two admins there — the maker and checker must be different principals.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/config_requests/test_user_type_requests.py -v`
Expected: FAIL — 422 on the propose call, because `"user_type"` is not in the `ConfigType` Literal.

- [ ] **Step 3: Wire the registry**

In `backend/app/shared/models/config_requests.py`, add the constant beside the others:

```python
CONFIG_TYPE_USER_TYPE = "user_type"
```

In `backend/app/modules/config_requests/schemas.py`, extend the Literal — **this is the step that is easy to miss.** FastAPI validates the Literal before any registry lookup runs, so omitting it produces a 422 that looks like a broken registry. This is exactly how `conversion_rate` failed when it was added:

```python
ConfigType = Literal[
    "pricing",
    "limit",
    "wallet_limit",
    "commission",
    "tax",
    "step_up",
    "conversion_rate",
    "user_type",
]
```

In `backend/app/modules/config_requests/apply.py`, add imports and one entry to each dispatch table:

```python
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type, replace_user_type_for_scope
from app.shared.models import CONFIG_TYPE_USER_TYPE, UserTypeDef

# _DISPATCH (create)
CONFIG_TYPE_USER_TYPE: (UserTypeCreateRequest, create_user_type),

# _REPLACE_DISPATCH (update — in place, see the service docstring)
CONFIG_TYPE_USER_TYPE: replace_user_type_for_scope,

# _MODEL_BY_TYPE
CONFIG_TYPE_USER_TYPE: UserTypeDef,

# _SCOPE_KEYS — scope is (tenant, code); one row per code
CONFIG_TYPE_USER_TYPE: ("code",),
```

Deliberately **omit** `CONFIG_TYPE_USER_TYPE` from `_DELETE_SCOPE_DISPATCH`. Then
find where `_DELETE_SCOPE_DISPATCH` is read and make a missing entry a clean
refusal rather than a `KeyError`:

```python
delete_fn = _DELETE_SCOPE_DISPATCH.get(config_type)
if delete_fn is None:
    raise AppHTTPException(
        422,
        "delete_not_supported",
        "This config type cannot be deleted; retire it instead.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/config_requests/ -v`
Expected: the two new tests PASS and every existing config-request test still passes.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/config_requests/ backend/app/shared/models/config_requests.py backend/tests/config_requests/test_user_type_requests.py
git commit -m "feat(user-types): route type changes through config maker-checker"
```

---

## Task 8: Identity — dynamic parent type and type validation

**Files:**
- Modify: `backend/app/modules/identity/service.py:180-204`
- Modify: `backend/app/shared/models/users.py:52-75`
- Test: `backend/tests/identity/test_dynamic_user_types.py`

- [ ] **Step 1: Write the failing test**

```python
"""Identity tests for dynamic user types and the type-driven parent rule."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type
from app.shared.exceptions import AppHTTPException
from app.shared.models import Role, Tenant


@pytest.mark.asyncio
async def test_user_can_be_created_with_a_custom_type(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify a user takes a tenant-created type — the whole point of the feature."""
    await create_user_type(
        db_session,
        UserTypeCreateRequest(tenant_id=test_tenant.id, code="distributor",
                              label="Distributor", category_code="retail"),
    )
    await db_session.commit()

    user = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825551234")],
            user_type="distributor",
        ),
    )
    assert user.user_type == "distributor"


@pytest.mark.asyncio
async def test_unknown_type_is_refused(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the service-level check replaces the dropped CHECK constraint."""
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[IdentifierIn(identifier_type="phone",
                                          identifier_value="+27825559999")],
                user_type="not_a_real_type",
            ),
        )
    assert exc.value.error_code == "unknown_user_type"


@pytest.mark.asyncio
async def test_parent_type_comes_from_the_type_row(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify a custom child type enforces its own declared parent type."""
    await create_user_type(
        db_session,
        UserTypeCreateRequest(tenant_id=test_tenant.id, code="distributor",
                              label="Distributor", category_code="retail"),
    )
    await create_user_type(
        db_session,
        UserTypeCreateRequest(tenant_id=test_tenant.id, code="sub_distributor",
                              label="Sub distributor", category_code="retail",
                              parent_type_code="distributor"),
    )
    await db_session.commit()

    boss = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825550001")],
            user_type="distributor",
        ),
    )
    child = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825550002")],
            user_type="sub_distributor",
            parent_user_id=boss.id,
        ),
    )
    assert child.parent_user_id == boss.id

    # A consumer cannot supervise a sub_distributor.
    wrong = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825550003")],
            user_type="consumer",
        ),
    )
    with pytest.raises(AppHTTPException):
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[IdentifierIn(identifier_type="phone",
                                          identifier_value="+27825550004")],
                user_type="sub_distributor",
                parent_user_id=wrong.id,
            ),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/identity/test_dynamic_user_types.py -v`
Expected: FAIL — `CreateUserRequest` rejects `"distributor"` because `user_type` is still the `UserType` Literal.

- [ ] **Step 3: Make the schema and validator dynamic**

In `backend/app/modules/identity/schemas.py`, replace line 20's Literal with a plain
string, keeping the constant available for defaults:

```python
# User types are configurable at runtime (user-types catalog, 2026-08-23), so
# this cannot be a Literal. Validity is enforced in the service against the
# tenant's own resolved list — see `user_types.service.get_user_type`.
UserType = str
```

In `backend/app/modules/identity/service.py`, replace the body of the parent
validator (currently lines 187-204) with:

```python
    child_type = await get_user_type(session, tenant_id, user_type)
    if child_type is None:
        raise UnknownUserType()

    expected_parent_type = child_type.parent_type_code

    # Types with no hierarchy slot must never carry a parent.
    if expected_parent_type is None:
        if parent_user_id is not None:
            raise InvalidUserTypeParent()
        return

    # Child types: parent stays OPTIONAL, but when present it must be the right
    # type AND live in the same tenant (no cross-tenant hierarchies).
    if parent_user_id is None:
        return

    result = await session.execute(
        select(User).where(User.id == parent_user_id, User.tenant_id == tenant_id)
    )
    parent = result.scalar_one_or_none()
    if parent is None or parent.user_type != expected_parent_type:
        raise InvalidUserTypeParent()
```

Ensure this validator runs on **every** user-creation path, so it also serves as
the replacement for the dropped CHECK. Replace `MERCHANT_USER_TYPES` membership
tests with `child_type.requires_merchant_profile`.

In `backend/app/shared/models/users.py`, delete `PARENT_TYPE_BY_CHILD` and
`MERCHANT_USER_TYPES`. Keep the five `USER_TYPE_*` constants — the seed and many
tests still use them as identifiers.

- [ ] **Step 4: Run the full identity and merchant suites**

Run: `cd backend && pytest tests/identity/ tests/merchant/ -v`
Expected: the three new tests PASS and every existing test still passes. Any
failure here means a `MERCHANT_USER_TYPES` or `PARENT_TYPE_BY_CHILD` reference
was missed — `grep -rn "MERCHANT_USER_TYPES\|PARENT_TYPE_BY_CHILD" app/` must
return nothing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/identity/ backend/app/shared/models/users.py backend/tests/identity/test_dynamic_user_types.py
git commit -m "feat(user-types): identity resolves parent type from the type row"
```

---

## Task 9: Attach a supervisor by identifier

**Files:**
- Modify: `backend/app/modules/identity/schemas.py`, `backend/app/modules/identity/service.py`
- Modify: `backend/app/modules/external/schemas.py`, `backend/app/modules/external/service.py`
- Test: `backend/tests/identity/test_parent_identifier.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for attaching a supervisor by phone number at onboarding (spec §7)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import CreateUserRequest, IdentifierIn, ParentIdentifierIn
from app.modules.identity.service import create_user
from app.shared.exceptions import AppHTTPException
from app.shared.models import Role, Tenant


async def _super_agent(session: AsyncSession, tenant: Tenant, phone: str):
    """Create a super-agent to act as the supervisor."""
    return await create_user(
        session,
        CreateUserRequest(
            tenant_id=tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value=phone)],
            user_type="super_agent",
        ),
    )


@pytest.mark.asyncio
async def test_agent_without_a_supervisor_succeeds(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the supervisor is genuinely optional — the common case."""
    agent = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825551000")],
            user_type="agent",
        ),
    )
    assert agent.parent_user_id is None


@pytest.mark.asyncio
async def test_supervisor_attaches_by_phone(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify parent_identifier resolves and attaches."""
    boss = await _super_agent(db_session, test_tenant, "+27825552000")
    agent = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825552001")],
            user_type="agent",
            parent_identifier=ParentIdentifierIn(
                identifier_type="phone", identifier_value="+27825552000"
            ),
        ),
    )
    assert agent.parent_user_id == boss.id


@pytest.mark.asyncio
async def test_both_parent_forms_is_ambiguous(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify parent_user_id and parent_identifier are mutually exclusive."""
    boss = await _super_agent(db_session, test_tenant, "+27825553000")
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[IdentifierIn(identifier_type="phone",
                                          identifier_value="+27825553001")],
                user_type="agent",
                parent_user_id=boss.id,
                parent_identifier=ParentIdentifierIn(
                    identifier_type="phone", identifier_value="+27825553000"
                ),
            ),
        )
    assert exc.value.error_code == "parent_reference_ambiguous"


@pytest.mark.asyncio
async def test_cross_tenant_supervisor_is_not_found(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant,
    default_user_role: Role, default_user_role_other_tenant: Role,
) -> None:
    """Verify a supervisor in another tenant looks identical to a missing one."""
    await _super_agent(db_session, other_tenant, "+27825554000")
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[IdentifierIn(identifier_type="phone",
                                          identifier_value="+27825554001")],
                user_type="agent",
                parent_identifier=ParentIdentifierIn(
                    identifier_type="phone", identifier_value="+27825554000"
                ),
            ),
        )
    assert exc.value.error_code == "parent_not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/identity/test_parent_identifier.py -v`
Expected: FAIL — `ImportError: cannot import name 'ParentIdentifierIn'`

- [ ] **Step 3: Add the schema and resolution**

In `backend/app/modules/identity/schemas.py`:

```python
class ParentIdentifierIn(BaseModel):
    """A supervisor named by one of their registered identifiers.

    Operators and partners hold phone numbers, not UUIDs, so this is the
    practical way to attach a supervisor at onboarding (spec §7.2).
    """

    identifier_type: Literal["phone", "email", "account", "card"]
    identifier_value: str = Field(min_length=1, max_length=255)
```

Add to `CreateUserRequest`:

```python
    # Mutually exclusive with `parent_user_id`. Both omitted is the normal case.
    parent_identifier: ParentIdentifierIn | None = None
```

Add the exceptions to `backend/app/shared/exceptions/__init__.py`:

```python
class ParentReferenceAmbiguous(AppHTTPException):
    """422 — both parent_user_id and parent_identifier were supplied."""

    def __init__(self) -> None:
        super().__init__(422, "parent_reference_ambiguous",
                         "Supply either parent_user_id or parent_identifier, not both.")


class ParentNotFound(AppHTTPException):
    """422 — the supervisor identifier does not resolve in this tenant.

    Deliberately does not distinguish "no such user" from "user in another
    tenant" — that difference would be an existence leak.
    """

    def __init__(self) -> None:
        super().__init__(422, "parent_not_found",
                         "No user in this tenant matches that identifier.")
```

In `backend/app/modules/identity/service.py`, add this helper and call it at the
top of `create_user`, before the parent validation:

```python
async def _resolve_parent_user_id(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    parent_user_id: UUID | None,
    parent_identifier: ParentIdentifierIn | None,
) -> UUID | None:
    """Collapse the two supervisor reference forms into one user id.

    Args:
        tenant_id: Resolution is tenant-scoped; a supervisor in another tenant
            is indistinguishable from a missing one.
        parent_user_id: Direct reference, or None.
        parent_identifier: Identifier reference, or None.

    Returns:
        The supervisor's user id, or None when neither form was supplied —
        which is valid and the normal case.

    Raises:
        ParentReferenceAmbiguous: both forms supplied.
        ParentNotFound: the identifier does not resolve in this tenant.
    """
    if parent_user_id is not None and parent_identifier is not None:
        raise ParentReferenceAmbiguous()
    if parent_identifier is None:
        return parent_user_id

    normalized = normalize_identifier(
        parent_identifier.identifier_type, parent_identifier.identifier_value
    )
    row = (
        await session.execute(
            select(UserIdentifier).where(
                UserIdentifier.tenant_id == tenant_id,
                UserIdentifier.identifier_type == parent_identifier.identifier_type,
                UserIdentifier.identifier_value == normalized,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ParentNotFound()
    return row.user_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/identity/test_parent_identifier.py -v`
Expected: 4 passed.

- [ ] **Step 5: Widen the partner onboarding API**

In `backend/app/modules/external/schemas.py`, add to `ExternalCreateUserRequest`:

```python
    # Optional — the endpoint defaulted to `consumer` with no parent before the
    # user-types catalog existed. The type is still validated against the API
    # key's own tenant, never trusted from the body.
    user_type: str = "consumer"
    parent_identifier: ParentIdentifierIn | None = None
```

Update its docstring, which currently says the endpoint forces consumer with no
parent. In `backend/app/modules/external/service.py`, pass both fields through to
`create_user` — the validation added above then applies unchanged.

First read one existing test in `backend/tests/external/test_external_users.py`
to copy its exact signing setup — partner requests need an HMAC signature over
the **raw** body, and there is already a fixture for it. The test below uses
`signed_post(path, body_dict)` as a stand-in name; **replace it with whatever
that file already calls**, and do not write a second signing helper.

```python
@pytest.mark.asyncio
async def test_partner_onboards_an_agent_with_a_supervisor(
    signed_post, db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the partner API can create a non-consumer and attach a supervisor."""
    boss = await signed_post("/api/v1/external/users", {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825556000"}],
        "user_type": "super_agent",
    })
    assert boss.status_code == 201, boss.text

    agent = await signed_post("/api/v1/external/users", {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825556001"}],
        "user_type": "agent",
        "parent_identifier": {"identifier_type": "phone", "identifier_value": "+27825556000"},
    })
    assert agent.status_code == 201, agent.text

    created = (await db_session.execute(
        select(User).where(User.id == UUID(agent.json()["id"]))
    )).scalar_one()
    assert created.user_type == "agent"
    assert created.parent_user_id == UUID(boss.json()["id"])


@pytest.mark.asyncio
async def test_partner_cannot_use_an_unknown_type(
    signed_post, test_tenant: Tenant
) -> None:
    """Verify widening the endpoint did not make it trust the body."""
    response = await signed_post("/api/v1/external/users", {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825557000"}],
        "user_type": "not_a_real_type",
    })
    assert response.status_code == 422
    assert response.json()["error_code"] == "unknown_user_type"


@pytest.mark.asyncio
async def test_partner_still_defaults_to_consumer(
    signed_post, db_session: AsyncSession, default_user_role: Role
) -> None:
    """Verify omitting user_type keeps the old behaviour for existing partners."""
    response = await signed_post("/api/v1/external/users", {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825558000"}],
    })
    assert response.status_code == 201, response.text
    created = (await db_session.execute(
        select(User).where(User.id == UUID(response.json()["id"]))
    )).scalar_one()
    assert created.user_type == "consumer"
    assert created.parent_user_id is None
```

- [ ] **Step 6: Run the external suite and commit**

Run: `cd backend && pytest tests/external/ tests/identity/ -v && make check`
Expected: all pass, ruff and mypy clean.

```bash
git add backend/app/modules/identity/ backend/app/modules/external/ backend/app/shared/exceptions/__init__.py backend/tests/identity/test_parent_identifier.py backend/tests/external/
git commit -m "feat(user-types): attach a supervisor by identifier at onboarding"
```

---

## Task 10: Admin UI — types and API client

**Files:**
- Modify: `admin-ui/lib/api-types.ts:14-45`
- Modify: `admin-ui/lib/api-endpoints.ts`
- Test: `admin-ui/lib/user-type-catalog.test.ts`

- [ ] **Step 1: Write the failing test**

Create `admin-ui/lib/user-type-catalog.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { groupTypesByCategory, topLevelTypes } from "@/lib/user-type-catalog";
import type { UserTypeCatalog } from "@/lib/api-types";

const catalog: UserTypeCatalog = {
  categories: [
    { code: "consumer", label: "Consumers", display_order: 1, supports_hierarchy: false },
    { code: "retail", label: "Retail", display_order: 2, supports_hierarchy: true },
  ],
  types: [
    { code: "consumer", label: "Consumer", category_code: "consumer", parent_type_code: null,
      is_system: true, status: "active", requires_merchant_profile: false },
    { code: "super_agent", label: "Super agent", category_code: "retail", parent_type_code: null,
      is_system: true, status: "active", requires_merchant_profile: false },
    { code: "agent", label: "Agent", category_code: "retail", parent_type_code: "super_agent",
      is_system: true, status: "active", requires_merchant_profile: false },
  ],
};

describe("user-type catalog helpers", () => {
  it("groups types under their category in display order", () => {
    const grouped = groupTypesByCategory(catalog);
    expect(grouped.map((g) => g.category.code)).toEqual(["consumer", "retail"]);
    expect(grouped[1].types.map((t) => t.code)).toEqual(["super_agent", "agent"]);
  });

  it("offers only top-level types as parent candidates", () => {
    // 'agent' is a child, so it must never be offered as somebody's parent —
    // this is the two-level cap expressed in the UI.
    expect(topLevelTypes(catalog, "retail").map((t) => t.code)).toEqual(["super_agent"]);
  });

  it("returns no parent candidates for a flat category", () => {
    expect(topLevelTypes(catalog, "consumer")).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin-ui && npx vitest run lib/user-type-catalog.test.ts`
Expected: FAIL — cannot resolve `@/lib/user-type-catalog`.

- [ ] **Step 3: Replace the literal union and add the helpers**

In `admin-ui/lib/api-types.ts`, delete the `UserType` literal union (line 18 area)
and the `USER_TYPES` array (line 37 area), and replace with:

```typescript
/**
 * A user type code. Types are configurable at runtime, so this is a plain
 * string — the valid set comes from `GET /api/v1/user-types`, not the type
 * system. Never hardcode a list of these again.
 */
export type UserType = string;

/** One user type as returned by the catalog endpoint. */
export interface UserTypeOption {
  code: string;
  label: string;
  category_code: string;
  parent_type_code: string | null;
  is_system: boolean;
  status: "active" | "retired";
  requires_merchant_profile: boolean;
}

/** One category. `supports_hierarchy` is false for Consumers. */
export interface UserTypeCategoryOption {
  code: string;
  label: string;
  display_order: number;
  supports_hierarchy: boolean;
}

/** The catalog endpoint's payload — both halves in one round trip. */
export interface UserTypeCatalog {
  categories: UserTypeCategoryOption[];
  types: UserTypeOption[];
}
```

Create `admin-ui/lib/user-type-catalog.ts`:

```typescript
/**
 * Pure helpers over the user-type catalog. No fetching — the caller supplies
 * the payload so these stay trivially testable.
 */
import type { UserTypeCatalog, UserTypeCategoryOption, UserTypeOption } from "@/lib/api-types";

/** A category with the types that belong to it, parents before their children. */
export interface CategoryGroup {
  category: UserTypeCategoryOption;
  types: UserTypeOption[];
}

/**
 * Group types under their category, categories in display order and, within a
 * category, top-level types before the children that hang off them.
 */
export function groupTypesByCategory(catalog: UserTypeCatalog): CategoryGroup[] {
  return [...catalog.categories]
    .sort((a, b) => a.display_order - b.display_order)
    .map((category) => ({
      category,
      types: catalog.types
        .filter((t) => t.category_code === category.code)
        .sort((a, b) => {
          // Parents first, then alphabetical — mirrors the indented list.
          const depth = Number(!!a.parent_type_code) - Number(!!b.parent_type_code);
          return depth !== 0 ? depth : a.label.localeCompare(b.label);
        }),
    }));
}

/**
 * The types that may be chosen as a parent in `categoryCode`: active,
 * top-level, same category. A child type is never offered, which is the
 * two-level cap expressed in the UI before the server ever refuses it.
 */
export function topLevelTypes(
  catalog: UserTypeCatalog,
  categoryCode: string,
): UserTypeOption[] {
  const category = catalog.categories.find((c) => c.code === categoryCode);
  if (!category?.supports_hierarchy) return [];
  return catalog.types.filter(
    (t) => t.category_code === categoryCode && !t.parent_type_code && t.status === "active",
  );
}
```

In `admin-ui/lib/api-endpoints.ts`, add the fetcher next to the other typed
endpoint functions, following their exact style:

```typescript
/** Fetch the user-type catalog for a tenant (categories + visible types). */
export async function fetchUserTypeCatalog(
  tenantId: string,
  opts: { includeRetired?: boolean } = {},
): Promise<UserTypeCatalog> {
  const q = new URLSearchParams({ tenant_id: tenantId });
  if (opts.includeRetired) q.set("include_retired", "true");
  return api<UserTypeCatalog>(`/api/v1/user-types?${q.toString()}`);
}
```

- [ ] **Step 4: Run test and the type check**

Run: `cd admin-ui && npx vitest run lib/user-type-catalog.test.ts && npx tsc --noEmit`
Expected: 3 tests pass. `tsc` will now report every site that relied on the
deleted `USER_TYPES` array — that list is the work for Task 11.

- [ ] **Step 5: Commit**

```bash
git add admin-ui/lib/api-types.ts admin-ui/lib/user-type-catalog.ts admin-ui/lib/user-type-catalog.test.ts admin-ui/lib/api-endpoints.ts
git commit -m "feat(user-types): dynamic UserType with catalog helpers"
```

---

## Task 11: `<UserTypeSelect>` and the six dialogs

**Files:**
- Create: `admin-ui/components/user-type-select.tsx`, `admin-ui/components/user-type-select.test.tsx`
- Modify: the six dialogs listed in spec §9

- [ ] **Step 1: Write the failing test**

Create `admin-ui/components/user-type-select.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UserTypeSelect } from "@/components/user-type-select";
import type { UserTypeCatalog } from "@/lib/api-types";

const catalog: UserTypeCatalog = {
  categories: [
    { code: "consumer", label: "Consumers", display_order: 1, supports_hierarchy: false },
    { code: "retail", label: "Retail", display_order: 2, supports_hierarchy: true },
  ],
  types: [
    { code: "consumer", label: "Consumer", category_code: "consumer", parent_type_code: null,
      is_system: true, status: "active", requires_merchant_profile: false },
    { code: "agent", label: "Agent", category_code: "retail", parent_type_code: "super_agent",
      is_system: true, status: "active", requires_merchant_profile: false },
  ],
};

describe("UserTypeSelect", () => {
  it("only offers types once a category is chosen", async () => {
    const user = userEvent.setup();
    render(<UserTypeSelect catalog={catalog} value={null} onChange={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: /user type/i })).toBeDisabled();

    await user.selectOptions(screen.getByRole("combobox", { name: /category/i }), "retail");
    expect(screen.getByRole("combobox", { name: /user type/i })).toBeEnabled();
    expect(screen.getByRole("option", { name: "Agent" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Consumer" })).not.toBeInTheDocument();
  });

  it("reports the chosen type code to the parent", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UserTypeSelect catalog={catalog} value={null} onChange={onChange} />);

    await user.selectOptions(screen.getByRole("combobox", { name: /category/i }), "retail");
    await user.selectOptions(screen.getByRole("combobox", { name: /user type/i }), "agent");
    expect(onChange).toHaveBeenCalledWith("agent");
  });

  it("preselects the category when given an existing value", () => {
    render(<UserTypeSelect catalog={catalog} value="agent" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: /category/i })).toHaveValue("retail");
    expect(screen.getByRole("combobox", { name: /user type/i })).toHaveValue("agent");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin-ui && npx vitest run components/user-type-select.test.tsx`
Expected: FAIL — cannot resolve `@/components/user-type-select`.

- [ ] **Step 3: Build the component**

Create `admin-ui/components/user-type-select.tsx`:

```typescript
/**
 * <UserTypeSelect> — the cascading category → user-type picker.
 *
 * Replaces the flat user-type dropdown everywhere a config is scoped to a type.
 * The operator narrows to a kind of customer first, which keeps the second list
 * short as tenants add their own types.
 *
 * Editing an existing config passes the stored code as `value`; the category is
 * derived from it so the control opens already narrowed.
 */
"use client";

import * as React from "react";

import type { UserTypeCatalog } from "@/lib/api-types";
import { groupTypesByCategory } from "@/lib/user-type-catalog";

export function UserTypeSelect({
  catalog,
  value,
  onChange,
  disabled = false,
}: {
  catalog: UserTypeCatalog;
  /** The stored type code, or null for "not chosen". */
  value: string | null;
  /** Fires with the chosen code, or null when the category is cleared. */
  onChange: (code: string | null) => void;
  disabled?: boolean;
}) {
  const groups = React.useMemo(() => groupTypesByCategory(catalog), [catalog]);
  const derivedCategory =
    catalog.types.find((t) => t.code === value)?.category_code ?? "";
  const [category, setCategory] = React.useState(derivedCategory);

  // Keep the category in step when the parent swaps `value` (e.g. editing a
  // different row without remounting).
  React.useEffect(() => setCategory(derivedCategory), [derivedCategory]);

  const typesInCategory = groups.find((g) => g.category.code === category)?.types ?? [];

  return (
    <div className="flex gap-2">
      <label className="flex-1">
        <span className="mb-1 block text-[11px] text-[--color-text-3]">Category</span>
        <select
          aria-label="Category"
          value={category}
          disabled={disabled}
          onChange={(e) => {
            setCategory(e.target.value);
            onChange(null); // the old type may not belong to the new category
          }}
          className="h-8 w-full rounded-md border border-[--color-border] bg-[--color-surface-1] px-2 text-[13px]"
        >
          <option value="">All customers</option>
          {groups.map((g) => (
            <option key={g.category.code} value={g.category.code}>
              {g.category.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex-1">
        <span className="mb-1 block text-[11px] text-[--color-text-3]">User type</span>
        <select
          aria-label="User type"
          value={value ?? ""}
          disabled={disabled || !category}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8 w-full rounded-md border border-[--color-border] bg-[--color-surface-1] px-2 text-[13px] disabled:opacity-50"
        >
          <option value="">Any</option>
          {typesInCategory.map((t) => (
            <option key={t.code} value={t.code}>
              {t.parent_type_code ? `  ${t.label}` : t.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd admin-ui && npx vitest run components/user-type-select.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Swap it into the six dialogs**

Replace the flat user-type `<select>` in each of these with `<UserTypeSelect>`,
passing the catalog fetched by the page's server component:

- `app/(authenticated)/limits/_components/create-limit-dialog.tsx`
- `app/(authenticated)/limits/_components/create-wallet-limit-dialog.tsx`
- `app/(authenticated)/commissions/_components/create-commission-dialog.tsx`
- `app/(authenticated)/taxes/_components/create-tax-dialog.tsx`
- `app/(authenticated)/services/_components/policy-controls.tsx`
- `app/(authenticated)/api-keys/_components/create-api-key-dialog.tsx` — this one
  filters to merchant-capable types. Replace the hardcoded
  `const MERCHANT_TYPES = ["merchant", "head_merchant"]` with
  `catalog.types.filter((t) => t.requires_merchant_profile)`.

Delete the now-dead label maps in `app/(authenticated)/users/_components/user-type-badge.tsx`,
`lib/user-operation-label.ts` and `services/_components/policy-controls.tsx`, replacing
their lookups with the catalog's `label`.

- [ ] **Step 6: Run the whole frontend suite**

Run: `cd admin-ui && npx tsc --noEmit && npm test && npm run lint`
Expected: no type errors, all tests pass, lint clean. Existing dialog tests will
need their fixtures updated to supply a `catalog` prop — that is expected work,
not a regression.

- [ ] **Step 7: Commit**

```bash
git add admin-ui/components/user-type-select.tsx admin-ui/components/user-type-select.test.tsx "admin-ui/app/(authenticated)"  admin-ui/lib
git commit -m "feat(user-types): cascading category-then-type picker across config dialogs"
```

---

## Task 12: The `/user-types` page

**Files:**
- Create: `admin-ui/app/(authenticated)/user-types/page.tsx`, `_actions.ts`, `_components/user-types-board.tsx`, `_components/create-user-type-dialog.tsx`, `_components/create-user-type-dialog.test.tsx`
- Modify: `admin-ui/components/app-shell/sidebar.tsx`, `admin-ui/components/command-palette/command-palette.tsx`

- [ ] **Step 1: Write the failing test**

Create `admin-ui/app/(authenticated)/user-types/_components/create-user-type-dialog.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateUserTypeDialog } from "@/app/(authenticated)/user-types/_components/create-user-type-dialog";
import type { UserTypeCatalog } from "@/lib/api-types";

const proposeUserTypeChangeAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/user-types/_actions", () => ({
  proposeUserTypeChangeAction: (...args: unknown[]) => proposeUserTypeChangeAction(...args),
}));

const catalog: UserTypeCatalog = {
  categories: [
    { code: "consumer", label: "Consumers", display_order: 1, supports_hierarchy: false },
    { code: "retail", label: "Retail", display_order: 2, supports_hierarchy: true },
  ],
  types: [
    { code: "super_agent", label: "Super agent", category_code: "retail",
      parent_type_code: null, is_system: true, status: "active",
      requires_merchant_profile: false },
    { code: "agent", label: "Agent", category_code: "retail",
      parent_type_code: "super_agent", is_system: true, status: "active",
      requires_merchant_profile: false },
  ],
};

beforeEach(() => vi.clearAllMocks());

describe("CreateUserTypeDialog", () => {
  it("hides the tier choice for a flat category", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);
    await user.selectOptions(screen.getByLabelText("Category"), "consumer");
    expect(screen.queryByLabelText(/sits under a parent/i)).not.toBeInTheDocument();
  });

  it("offers only top-level types as parents", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);
    await user.selectOptions(screen.getByLabelText("Category"), "retail");
    await user.click(screen.getByLabelText(/sits under a parent/i));

    expect(screen.getByRole("option", { name: "Super agent" })).toBeInTheDocument();
    // 'Agent' is itself a child — offering it would build a third level.
    expect(screen.queryByRole("option", { name: "Agent" })).not.toBeInTheDocument();
  });

  it("proposes a create with the parent attached", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(screen.getByLabelText("Code"), "junior_agent");
    await user.type(screen.getByLabelText("Label"), "Junior agent");
    await user.selectOptions(screen.getByLabelText("Category"), "retail");
    await user.click(screen.getByLabelText(/sits under a parent/i));
    await user.selectOptions(screen.getByLabelText("Parent type"), "super_agent");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      tenant_id: "t1",
      code: "junior_agent",
      label: "Junior agent",
      category_code: "retail",
      parent_type_code: "super_agent",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin-ui && npx vitest run "app/(authenticated)/user-types"`
Expected: FAIL — module not found.

- [ ] **Step 3: Build the action, dialog, board and page**

`_actions.ts` — follow `app/(authenticated)/redemption-rates/_actions.ts` exactly:
a `"use server"` module whose `proposeUserTypeChangeAction(payload)` posts to
`/api/v1/config-requests` with `config_type: "user_type"`, `operation: "create"`,
then `revalidatePath("/user-types")`. Add `proposeUserTypeUpdateAction(tenantId,
code, payload)` for relabel/retire, using `operation: "update"`.

`_components/create-user-type-dialog.tsx` — fields in this order: Code (lowercase,
`^[a-z][a-z0-9_]*$`, immutable after creation so it is validated hard here),
Label, Category. When the chosen category has `supports_hierarchy`, show a
checkbox labelled "This type sits under a parent"; when ticked, a required
"Parent type" select populated from `topLevelTypes(catalog, category)`. Also a
"Requires a merchant profile" checkbox, defaulting to true when the category is
Business. Submit calls `proposeUserTypeChangeAction`.

`_components/user-types-board.tsx` — one section per category in display order.
Retail and Business render parents with their children indented beneath; Consumers
renders flat. Each row: label, `<code>code</code>`, a `<StatusPill>` for
active/retired, a "System" badge where `is_system`. Rows with `is_system` show no
edit or retire affordance at all — absent, not disabled.

`page.tsx` — a server component that reads `getActiveTenantId()`, fetches the
catalog with `includeRetired: true`, and renders `<PageHeader>` plus the board.
Follow `app/(authenticated)/redemption-rates/page.tsx` for the shape, including
its "no active tenant" empty state.

Add to `admin-ui/components/app-shell/sidebar.tsx` near the other configuration
entries: `{ label: "User types", href: "/user-types", icon: Users2 }`, and the
matching `{ label: "Go to User types", href: "/user-types", icon: Users2 }` in
`command-palette.tsx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd admin-ui && npx vitest run "app/(authenticated)/user-types" && npx tsc --noEmit`
Expected: 3 passed, no type errors.

- [ ] **Step 5: Commit**

```bash
git add "admin-ui/app/(authenticated)/user-types" admin-ui/components/app-shell/sidebar.tsx admin-ui/components/command-palette/command-palette.tsx
git commit -m "feat(user-types): /user-types page with maker-checker proposals"
```

---

## Task 13: Supervisor lookup in the create-user dialog

**Files:**
- Create: `admin-ui/app/(authenticated)/users/_components/supervisor-picker.tsx` + test
- Modify: `admin-ui/app/(authenticated)/users/_components/create-user-dialog.tsx`, `_actions.ts`

- [ ] **Step 1: Write the failing test**

Create `admin-ui/app/(authenticated)/users/_components/supervisor-picker.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SupervisorPicker } from "@/app/(authenticated)/users/_components/supervisor-picker";

const lookupUserAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  lookupUserAction: (...args: unknown[]) => lookupUserAction(...args),
}));

beforeEach(() => vi.clearAllMocks());

describe("SupervisorPicker", () => {
  it("shows the resolved person for confirmation before attaching", async () => {
    lookupUserAction.mockResolvedValue({
      ok: true,
      user: { id: "u1", full_name: "Thabo Nkosi", user_type: "super_agent",
              masked_phone: "+27 82 *** 0142" },
    });
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <SupervisorPicker requiredType="super_agent" requiredTypeLabel="Super agent"
                        value={null} onChange={onChange} />,
    );

    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825550142");
    await user.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByText("Thabo Nkosi")).toBeInTheDocument();
    expect(screen.getByText("+27 82 *** 0142")).toBeInTheDocument();
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("+27825550142"));
  });

  it("names the required type when the wrong person is found", async () => {
    lookupUserAction.mockResolvedValue({
      ok: true,
      user: { id: "u2", full_name: "Ada Mensah", user_type: "consumer",
              masked_phone: "+27 82 *** 0199" },
    });
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <SupervisorPicker requiredType="super_agent" requiredTypeLabel="Super agent"
                        value={null} onChange={onChange} />,
    );

    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825550199");
    await user.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByText(/must be a Super agent/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith("+27825550199");
  });

  it("clears an attached supervisor", async () => {
    lookupUserAction.mockResolvedValue({
      ok: true,
      user: { id: "u1", full_name: "Thabo Nkosi", user_type: "super_agent",
              masked_phone: "+27 82 *** 0142" },
    });
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <SupervisorPicker requiredType="super_agent" requiredTypeLabel="Super agent"
                        value={null} onChange={onChange} />,
    );
    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825550142");
    await user.click(screen.getByRole("button", { name: "Look up" }));
    await screen.findByText("Thabo Nkosi");

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin-ui && npx vitest run "app/(authenticated)/users/_components/supervisor-picker.test.tsx"`
Expected: FAIL — module not found.

- [ ] **Step 3: Build the picker and wire the dialog**

`supervisor-picker.tsx` — a phone field, a **Look up** button, and three states:
empty, resolved (name, type label, masked phone, **Clear**), and error. On a
resolved user whose `user_type` differs from `requiredType`, render
`Supervisor must be a {requiredTypeLabel}.` and do **not** report the value
upward. On success call `onChange(phone)` — the parent sends
`parent_identifier`, not an id, so the backend re-resolves and re-validates.
Reuse the lookup pattern in `user-lookup-form.tsx`; do not write a second one.

In `create-user-dialog.tsx`, render `<SupervisorPicker>` only when the selected
type has a non-null `parent_type_code`, labelled "Supervisor (optional)". Pass
`requiredTypeLabel` from the catalog entry for that `parent_type_code`. Include
`parent_identifier: { identifier_type: "phone", identifier_value: phone }` in the
create payload when set, and omit the key entirely when not.

Add `lookupUserAction` to `users/_actions.ts` if it does not already exist,
wrapping `GET /api/v1/resolve/phone/{value}` and returning the masked phone.
**Never return an unmasked phone to the client** — `shared/utils/masking.py` has
the helper and NFR-0240 requires it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd admin-ui && npx vitest run "app/(authenticated)/users" && npx tsc --noEmit`
Expected: 3 new tests pass, existing user tests still pass.

- [ ] **Step 5: Commit**

```bash
git add "admin-ui/app/(authenticated)/users"
git commit -m "feat(user-types): attach a supervisor by phone lookup at user creation"
```

---

## Task 14: Seed, docs and full verification

**Files:**
- Modify: `scripts/seed.py`, `CLAUDE.md`, `docs/09-epics-and-stories.md`

- [ ] **Step 1: Make the seed idempotent against the catalog**

`scripts/seed.py` creates users with hardcoded type strings. Those still work —
the codes are unchanged — but add a guard near the top of the user-seeding
section that asserts the five system types exist, so a seed run against a
database that missed the migration fails loudly:

```python
existing = (await session.execute(
    select(UserTypeDef.code).where(UserTypeDef.tenant_id.is_(None))
)).scalars().all()
missing = {"consumer", "agent", "super_agent", "merchant", "head_merchant"} - set(existing)
if missing:
    raise SystemExit(f"User-type catalog not seeded (missing: {sorted(missing)}). "
                     "Run `alembic upgrade head` first.")
```

- [ ] **Step 2: Update the docs**

In `CLAUDE.md`, the repo-layout table gains a `user_types` row. In
`docs/09-epics-and-stories.md`, add the epic entry, its index row, and bump the
totals — follow the format of the SEC and VAPT entries already in Section 7.

- [ ] **Step 3: Full verification**

Run:

```bash
cd backend && make check && make test
cd ../admin-ui && npx tsc --noEmit && npm run lint && npm test && npm run build
```

Expected: alembic check clean, ruff and mypy clean, full pytest suite green,
no TypeScript errors, all Vitest suites green, production build succeeds.

- [ ] **Step 4: Confirm nothing hardcoded survives**

Run:

```bash
grep -rn "MERCHANT_USER_TYPES\|PARENT_TYPE_BY_CHILD" backend/app/
grep -rn '"head_merchant"' admin-ui/app admin-ui/lib admin-ui/components --include="*.ts" --include="*.tsx" | grep -v test
```

Expected: both return nothing. Any hit is a hardcoded list that will not see
custom types — the exact defect this feature exists to remove.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed.py CLAUDE.md docs/09-epics-and-stories.md
git commit -m "docs(user-types): seed guard, repo layout and backlog entry"
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| §4.1, §4.2 data model | 1, 2 |
| §4.3 seed | 2 |
| §5 behavioural flags + four hierarchy rules | 4, 8 |
| §6 resolution and validation | 3, 4, 8 |
| §7.1–7.2 parent by identifier | 9 |
| §7.3 partner API | 9 |
| §7.4 admin supervisor lookup | 13 |
| §8 maker-checker | 7 |
| §9 admin UI | 10, 11, 12 |
| §10 migration, drop CHECK, downgrade guard | 2 |
| §11 risks — retired types stay resolvable | 3 (test), 5 (retire guard) |
| §12 testing | every task; Task 14 runs the whole suite |
| §13 out of scope | not implemented, by design |
