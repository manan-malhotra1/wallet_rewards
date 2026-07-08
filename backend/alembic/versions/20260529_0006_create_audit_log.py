"""create audit_log table (PRD §6.13)

Phase E.1 — used by reconciliation; reused by every state-changing endpoint
in Phase F. Append-only by convention: no `updated_at` column.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
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
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # No updated_at column — audit entries are immutable (NFR-0160).
        sa.CheckConstraint(
            "actor_type IN ('user', 'admin', 'system')",
            name="ck_audit_log_actor_type",
        ),
    )
    op.create_index(
        "idx_audit_entity",
        "audit_log",
        ["entity_type", "entity_id", "created_at"],
    )
    op.create_index("idx_audit_actor", "audit_log", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_actor", table_name="audit_log")
    op.drop_index("idx_audit_entity", table_name="audit_log")
    op.drop_table("audit_log")
