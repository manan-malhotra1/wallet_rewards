"""add merchant_user_id to api_keys (merchant_cashin funding source)

A merchant-bound API key carries `merchant_user_id`, the user whose wallet is
debited when the key calls `POST /api/v1/external/merchant-cashin`. Existing
partner keys leave it NULL (fund/withdraw ignore the column), so they are
unaffected. Nullable FK -> users.id, indexed. No data backfill.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable, indexed merchant_user_id FK column to api_keys."""
    op.add_column(
        "api_keys",
        sa.Column("merchant_user_id", sa.UUID(), nullable=True),
    )
    op.create_index("ix_api_keys_merchant_user_id", "api_keys", ["merchant_user_id"])
    op.create_foreign_key(
        "fk_api_keys_merchant_user_id_users",
        "api_keys",
        "users",
        ["merchant_user_id"],
        ["id"],
    )


def downgrade() -> None:
    """Drop the FK, index, and column. Safe — nothing references it."""
    op.drop_constraint("fk_api_keys_merchant_user_id_users", "api_keys", type_="foreignkey")
    op.drop_index("ix_api_keys_merchant_user_id", table_name="api_keys")
    op.drop_column("api_keys", "merchant_user_id")
