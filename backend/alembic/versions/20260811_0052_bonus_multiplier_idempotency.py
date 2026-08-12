"""bonus_multipliers.idempotency_key — create-path replay guard

Adds a nullable `idempotency_key` to `bonus_multipliers` plus the
`(tenant_id, idempotency_key)` unique constraint, so a replayed
POST /api/v1/multipliers returns the original row instead of inserting a
duplicate (Pay-PRD-0200 / repo invariant #2). Nullable because rows created
before this change carry no key — Postgres treats NULLs as distinct, so
legacy rows never collide.

Revision ID: 0052
Revises: 0051
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable idempotency_key column + per-tenant unique constraint."""
    op.add_column(
        "bonus_multipliers",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_bonus_multipliers_idempotency_per_tenant",
        "bonus_multipliers",
        ["tenant_id", "idempotency_key"],
    )


def downgrade() -> None:
    """Drop the unique constraint and the idempotency_key column."""
    op.drop_constraint(
        "uq_bonus_multipliers_idempotency_per_tenant",
        "bonus_multipliers",
        type_="unique",
    )
    op.drop_column("bonus_multipliers", "idempotency_key")
