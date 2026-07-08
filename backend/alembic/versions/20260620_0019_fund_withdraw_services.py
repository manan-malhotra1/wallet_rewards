"""Backfill `fund` and `withdraw` into the services catalog (Phase 4).

Phase 4 of the Tenant Management refactor formalises the two admin-side
money-movement services as first-class entries in the services catalog
so they appear in Limits / Pricing / Campaigns dropdowns alongside p2p,
airtime_recharge and redemption.

No schema changes — pure data backfill, idempotent via ON CONFLICT.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, display_name, description) for the two new entries.
_PHASE_4_SERVICES: list[tuple[str, str, str]] = [
    (
        "fund",
        "Fund",
        "Admin credits a user's wallet from the operator cash pool.",
    ),
    (
        "withdraw",
        "Withdraw",
        "Admin debits a user's wallet and returns funds to the operator cash pool.",
    ),
]


def upgrade() -> None:
    """Insert fund + withdraw into every existing tenant's catalog."""
    bind = op.get_bind()
    tenant_ids = (
        bind.execute(sa.text("SELECT id FROM tenants WHERE deleted_at IS NULL")).scalars().all()
    )

    for tenant_id in tenant_ids:
        for code, display_name, description in _PHASE_4_SERVICES:
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
    """Remove the fund + withdraw rows. Hard delete; the partial-unique
    index lets a follow-up upgrade re-insert them."""
    op.execute("DELETE FROM services WHERE code IN ('fund', 'withdraw') AND deleted_at IS NULL")
