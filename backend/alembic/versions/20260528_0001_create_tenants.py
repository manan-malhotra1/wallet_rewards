"""create tenants and tenant_config tables (PRD §6.1)

Revision ID: 0001
Revises:
Create Date: 2026-05-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("deployment_mode", sa.String(length=20), nullable=False),
        sa.Column("base_currency", sa.CHAR(length=3), nullable=False),
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
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "deployment_mode IN ('wallet', 'rewards_only')",
            name="ck_tenants_deployment_mode",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_tenants_status",
        ),
    )

    op.create_table(
        "tenant_config",
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
        sa.Column("config_key", sa.String(length=100), nullable=False),
        sa.Column("config_value", sa.Text(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "config_key", name="uq_tenant_config_key"),
    )
    op.create_index("ix_tenant_config_tenant_id", "tenant_config", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_config_tenant_id", table_name="tenant_config")
    op.drop_table("tenant_config")
    op.drop_table("tenants")
