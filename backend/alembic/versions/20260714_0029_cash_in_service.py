"""Backfill `cash_in` into the services catalog (Pricing v2 Epic 21)

Story 21.1 — registers the agent cash-in service so it appears in Limits /
Pricing / Commission / Tax dropdowns alongside p2p, airtime_recharge, etc. Pure
data backfill, idempotent via ON CONFLICT.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASH_IN = (
    "cash_in",
    "Cash In",
    "An agent funds a customer's wallet from the agent's e-float and earns a commission.",
)


def upgrade() -> None:
    """Insert cash_in into every existing tenant's catalog."""
    bind = op.get_bind()
    tenant_ids = (
        bind.execute(sa.text("SELECT id FROM tenants WHERE deleted_at IS NULL")).scalars().all()
    )
    code, display_name, description = _CASH_IN
    for tenant_id in tenant_ids:
        bind.execute(
            sa.text(
                "INSERT INTO services "
                "(tenant_id, code, display_name, description) "
                "VALUES (:tenant_id, :code, :display_name, :description) "
                "ON CONFLICT DO NOTHING"
            ).bindparams(
                tenant_id=tenant_id,
                code=code,
                display_name=display_name,
                description=description,
            )
        )


def downgrade() -> None:
    """Remove the cash_in service rows."""
    op.execute("DELETE FROM services WHERE code = 'cash_in' AND deleted_at IS NULL")
