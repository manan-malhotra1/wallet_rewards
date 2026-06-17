"""create step_up_policies table

Tenant-configurable per-(transaction_type, currency) PIN-step-up
thresholds. A user-initiated transaction with `amount > threshold`
requires the user to re-enter their PIN; below the threshold the
session token alone is enough.

Separate from `limit_configs` because the semantics differ:
limits REJECT past the cap; step-up ESCALATES past the threshold.
Mixing them in one table would tangle the rejection vs prompt logic.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-16

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the step_up_policies table + supporting indexes."""
    op.create_table(
        "step_up_policies",
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
        sa.Column("transaction_type", sa.String(50), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("threshold_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "threshold_amount >= 0", name="ck_step_up_policies_threshold_nonneg"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "transaction_type",
            "currency",
            name="uq_step_up_policies_scope",
        ),
    )
    op.create_index(
        "ix_step_up_policies_tenant",
        "step_up_policies",
        ["tenant_id"],
    )


def downgrade() -> None:
    """Drop the table — safe because no other table references it."""
    op.drop_index("ix_step_up_policies_tenant", table_name="step_up_policies")
    op.drop_table("step_up_policies")
