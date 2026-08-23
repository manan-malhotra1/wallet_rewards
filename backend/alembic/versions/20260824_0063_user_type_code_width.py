"""narrow user_types.code and user_types.parent_type_code to VARCHAR(20)

`user_types.code` was VARCHAR(30) while every column that stores it —
`users.user_type` and the `user_type` column on the limit / wallet_limit /
pricing / commission config tables — is VARCHAR(20). A tenant could therefore
create a 21-30 character code and then hit a raw `DataError` (500) the moment a
user or config row was written with it.

Narrowing the catalog is the cheap side of the fix: `users` is a large hot table
and widening it for ten extra characters in a machine identifier is
disproportionate — the operator-facing name lives in `label`, which has 60.
`parent_type_code` holds another row's `code`, so it moves with it.

Safe to apply: the 20-character cap is enforced at the schema boundary
(`UserTypeCreateRequest`), and every seeded system code is well under it. The
ALTER fails loudly rather than truncating if a longer value somehow exists.

Revision ID: 0063
Revises: 0062
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0063"
down_revision: str | Sequence[str] | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "user_types"
_COLUMNS = (("code", False), ("parent_type_code", True))


def upgrade() -> None:
    """Narrow both code columns from VARCHAR(30) to VARCHAR(20).

    Side effects:
        Rewrites the `user_types` column types. PostgreSQL refuses the ALTER —
        it does not truncate — if any existing value exceeds 20 characters.
    """
    for column, nullable in _COLUMNS:
        op.alter_column(
            _TABLE,
            column,
            existing_type=sa.String(30),
            type_=sa.String(20),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    """Widen both code columns back to VARCHAR(30)."""
    for column, nullable in _COLUMNS:
        op.alter_column(
            _TABLE,
            column,
            existing_type=sa.String(20),
            type_=sa.String(30),
            existing_nullable=nullable,
        )
