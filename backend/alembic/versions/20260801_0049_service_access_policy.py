"""per-service access policy (allowed_user_types + allowed_channels) on services

Adds two nullable Postgres text-array columns to `services` that together form
the single source of truth for WHO (user_type) may initiate a service and via
WHICH channel. NULL or an empty array on either column means "no restriction on
that dimension"; a non-empty array is an allow-list. Existing rows are
backfilled BY CODE with sensible defaults (see `_POLICY_BY_CODE`) so current
behaviour is preserved while the policy becomes explicit. The backfill mirrors
`SERVICE_POLICY` in app/modules/tenants/service.py used by a fresh seed.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Code -> (allowed_user_types, allowed_channels). Kept as literals (not an app
# import) so this migration stays stable if the app constant later drifts. MUST
# stay in sync with SERVICE_POLICY in app/modules/tenants/service.py.
_POLICY_BY_CODE: dict[str, tuple[list[str], list[str]]] = {
    "p2p": (["consumer"], ["mobile"]),
    "airtime_recharge": (["consumer"], ["mobile"]),
    "redemption": (["consumer"], ["mobile"]),
    "cashout": (["consumer"], ["mobile"]),
    "change_pin": (["consumer"], ["mobile"]),
    "cash_in": (["agent", "super_agent"], ["mobile"]),
    "merchant_cashin": (["merchant", "head_merchant"], ["api"]),
    "fund": ([], ["admin", "api"]),
    "withdraw": ([], ["admin", "api"]),
}


def upgrade() -> None:
    """Add the two nullable array columns, then backfill existing rows by code."""
    op.add_column(
        "services",
        sa.Column("allowed_user_types", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "services",
        sa.Column("allowed_channels", postgresql.ARRAY(sa.String()), nullable=True),
    )

    # Backfill every existing service row by its code. A code not present in the
    # map is left NULL/NULL (unrestricted). tenant_id-agnostic on purpose: the
    # policy is a property of the service's code, identical across tenants.
    services = sa.table(
        "services",
        sa.column("code", sa.String),
        sa.column("allowed_user_types", postgresql.ARRAY(sa.String())),
        sa.column("allowed_channels", postgresql.ARRAY(sa.String())),
    )
    for code, (user_types, channels) in _POLICY_BY_CODE.items():
        op.execute(
            services.update()
            .where(services.c.code == code)
            .values(allowed_user_types=user_types, allowed_channels=channels)
        )


def downgrade() -> None:
    """Drop both access-policy columns."""
    op.drop_column("services", "allowed_channels")
    op.drop_column("services", "allowed_user_types")
