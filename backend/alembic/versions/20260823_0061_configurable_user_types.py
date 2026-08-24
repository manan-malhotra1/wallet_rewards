"""Configurable user types: categories, types, seed, drop users CHECK.

Creates the two-table user-type catalog (`user_type_categories`, `user_types`)
that replaces the five hardcoded constants in `app/shared/models/users.py`, and
seeds it with the three fixed categories and the five system types (spec §4.3).

Steps 1-3 are additive and reversible. Step 4 — dropping `ck_users_user_type` —
is the one-way door: the downgrade recreates the CHECK, which fails if any
non-system type is already in use, so the downgrade aborts loudly instead of
half-applying.

Revision ID: 0061
Revises: 0060
Create Date: 2026-08-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
    """Create the catalog tables, seed them, and drop the users CHECK.

    Side effects:
        Inserts three `user_type_categories` rows and five system
        `user_types` rows, then drops `ck_users_user_type` from `users`.
        After this migration `users.user_type` is validated in the service
        layer only (spec §11) — the database no longer constrains it.
    """
    op.create_table(
        "user_type_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supports_hierarchy", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "user_types",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=True,
        ),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column(
            "category_code",
            sa.String(30),
            sa.ForeignKey("user_type_categories.code"),
            nullable=False,
        ),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "requires_merchant_profile", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("parent_type_code", sa.String(30), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_user_types_status"),
        sa.CheckConstraint(
            "parent_type_code IS NULL OR parent_type_code <> code",
            name="ck_user_types_no_self_parent",
        ),
    )
    # Both FK columns are indexed per .claude/rules/database.md. Names must
    # match SQLAlchemy's `index=True` default (`ix_<table>_<column>`) or
    # `alembic check` reports permanent drift.
    op.create_index("ix_user_types_tenant_id", "user_types", ["tenant_id"])
    op.create_index("ix_user_types_category_code", "user_types", ["category_code"])
    # Two partial indexes, not one composite: a system code must be globally
    # unique, which a composite on (tenant_id, code) cannot express when
    # tenant_id is NULL.
    op.create_index(
        "uq_user_types_system_code",
        "user_types",
        ["code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_user_types_tenant_code",
        "user_types",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )

    categories = sa.table(
        "user_type_categories",
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("supports_hierarchy", sa.Boolean),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(
        categories,
        [
            {
                "code": code,
                "label": label,
                "display_order": order,
                "supports_hierarchy": hierarchy,
                "is_system": True,
            }
            for code, label, order, hierarchy in _CATEGORIES
        ],
    )

    types = sa.table(
        "user_types",
        sa.column("tenant_id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("category_code", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("status", sa.String),
        sa.column("requires_merchant_profile", sa.Boolean),
        sa.column("parent_type_code", sa.String),
    )
    op.bulk_insert(
        types,
        [
            {
                "tenant_id": None,
                "code": code,
                "label": label,
                "category_code": category,
                "is_system": True,
                "status": "active",
                "requires_merchant_profile": merchant_profile,
                "parent_type_code": parent,
            }
            for code, label, category, merchant_profile, parent in _TYPES
        ],
    )

    # The one-way door. Dynamic types cannot live behind a static allowlist.
    op.drop_constraint("ck_users_user_type", "users", type_="check")


def downgrade() -> None:
    """Recreate the CHECK and drop the catalog — aborts if custom types exist.

    Raises:
        RuntimeError: a non-system (`is_system = false`) user type exists.
            Recreating the static CHECK would then either fail or silently
            orphan users carrying that type, so we refuse rather than
            half-apply.
    """
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
    op.drop_index("ix_user_types_category_code", table_name="user_types")
    op.drop_index("ix_user_types_tenant_id", table_name="user_types")
    op.drop_table("user_types")
    op.drop_table("user_type_categories")
