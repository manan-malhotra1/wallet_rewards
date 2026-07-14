"""extend ck_accounts_type with commission and taxes

Adds two Pricing v2 (Epic 19) system account types:
  - `commission`: platform-funded pool. A commission paid to an agent is
    DEBITed here and CREDITed to the agent wallet; the operator tops it up.
  - `taxes`: tax collector. Every tax leg (on a fee or a commission) CREDITs
    this account.

Both are lazy-created per (tenant, currency) by the pricing service and are
skipped by the balance guard (they may run "negative"/unbounded by design).

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-14

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALLOWED_TYPES = (
    "financial_wallet",
    "points_account",
    "system_points_issuance",
    "provider_redemption_wallet",
    "system_cash_inflow",
    "system_fee_collected",
    "operator_adjustment",
    "airtime_merchant_holding",
    "commission",
    "taxes",
)

NEW_TYPES = ("commission", "taxes")


def upgrade() -> None:
    """Drop and recreate ck_accounts_type with commission + taxes included."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    types_sql = ", ".join(f"'{t}'" for t in ALLOWED_TYPES)
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        f"account_type IN ({types_sql})",
    )


def downgrade() -> None:
    """Restore the prior 8-value CHECK constraint (drops commission + taxes)."""
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    types_sql = ", ".join(f"'{t}'" for t in ALLOWED_TYPES if t not in NEW_TYPES)
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        f"account_type IN ({types_sql})",
    )
