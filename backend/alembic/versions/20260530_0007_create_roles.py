"""create roles, role_permissions, user_roles tables (PRD §6.4)

Phase F.3 — Module 7. Roles gate which transaction types a user can
initiate. Per-tenant, per-role permissions; many-to-many between users and
roles.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- roles -------------------------------------------------------------
    op.create_table(
        "roles",
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
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_name_per_tenant"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_roles_status",
        ),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    # -- role_permissions --------------------------------------------------
    op.create_table(
        "role_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id"),
            nullable=False,
        ),
        sa.Column("transaction_type", sa.String(length=50), nullable=False),
        sa.Column(
            "permitted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.UniqueConstraint(
            "role_id",
            "transaction_type",
            name="uq_role_permissions_per_type",
        ),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])

    # -- user_roles --------------------------------------------------------
    op.create_table(
        "user_roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_pair"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index("ix_roles_tenant_id", table_name="roles")
    op.drop_table("roles")
