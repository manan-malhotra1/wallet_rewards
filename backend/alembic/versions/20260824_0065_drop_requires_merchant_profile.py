"""drop user_types.requires_merchant_profile — capability follows the category

The flag's name overpromised. Nothing in `app/` ever constructed a
`MerchantProfile` row or a collection account off it; its single real effect was
gating which users a merchant-bound API key could attach to. That is now derived
from `category_code = 'business'`, exactly as cash-out eligibility is derived
from `category_code = 'retail'` (`cashout/service.py`) — Consumers / Retail /
Business are what the three categories mean, and the two seeded Business types
(`merchant`, `head_merchant`) were precisely the two that carried the flag.

Dropping the column rather than just hiding its checkbox is what keeps a custom
Business type bindable to an API key: left in place and un-settable, such a type
would have been permanently un-bindable with no way to fix it.

Revision ID: 0065
Revises: 0064
Create Date: 2026-08-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The category whose types the flag encoded. Kept as a literal, not imported
# from `app.shared.models`: a migration must keep describing the schema as it
# was on the day it ran, even after the constant moves or is renamed.
_MERCHANT_CATEGORY = "business"


def upgrade() -> None:
    """Drop the `requires_merchant_profile` column from `user_types`.

    Side effects:
        Removes the column outright. No data migration is needed on the way up:
        the information it held is already implied by `category_code`, which
        every row carries and which the API-key merchant check now reads.
    """
    op.drop_column("user_types", "requires_merchant_profile")


def downgrade() -> None:
    """Re-add the column and backfill it from the category.

    A plain re-add would land every row on the `false` server default, silently
    resetting `merchant` and `head_merchant` — and any tenant's Business type —
    to "not merchant-capable", which is exactly the regression this change set
    out to avoid. Backfilling from `category_code` makes the round trip lossless
    for every row the upgrade could have dropped a `true` from.

    Side effects:
        Adds `requires_merchant_profile` (NOT NULL, default false) and sets it
        true for every Business-category row before returning.
    """
    op.add_column(
        "user_types",
        sa.Column(
            "requires_merchant_profile", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    # Bound parameter, not interpolation — the value is data, not an identifier.
    op.get_bind().execute(
        sa.text(
            "UPDATE user_types SET requires_merchant_profile = true WHERE category_code = :category"
        ),
        {"category": _MERCHANT_CATEGORY},
    )
