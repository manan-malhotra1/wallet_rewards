"""create external_user_creations (partner create-user idempotency anchor)

Partner create-user posts no ledger transaction, so it has no
`transactions.idempotency_key` to dedup on. This table records each successful
external create's `(tenant_id, idempotency_key)` -> `user_id` so a retry with
the same key replays the original user rather than creating a second one or
leaking a 409 (Pay-PRD-0200). No PII is stored — only the key and the FK.

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the external_user_creations table with its idempotency + FKs."""
    op.create_table(
        "external_user_creations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_external_user_creations_idempotency_per_tenant",
        ),
    )
    op.create_index(
        "ix_external_user_creations_tenant", "external_user_creations", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_external_user_creations_user", "external_user_creations", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Drop the external_user_creations table and its indexes."""
    op.drop_index("ix_external_user_creations_user", table_name="external_user_creations")
    op.drop_index("ix_external_user_creations_tenant", table_name="external_user_creations")
    op.drop_table("external_user_creations")
