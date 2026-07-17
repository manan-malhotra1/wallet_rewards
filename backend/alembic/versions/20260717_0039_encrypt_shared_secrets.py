"""encrypt callback/event shared secrets at rest (Fernet, Decision D3)

Moves `redemption_providers.shared_secret` and
`external_event_sources.shared_secret` from plaintext to Fernet-encrypted
`shared_secret_encrypted` columns, mirroring `api_keys.secret_encrypted` and
`merchant_profiles.callback_secret_encrypted`. Existing non-NULL values are
re-encrypted in place; NULLs stay NULL. Downgrade decrypts back to plaintext.

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-17 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.auth.secret_box import decrypt_secret, encrypt_secret

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables carrying a plaintext HMAC shared secret that must be encrypted at rest.
_TABLES = ("redemption_providers", "external_event_sources")


def _migrate_secrets(table: str, src_col: str, dst_col: str, transform) -> None:
    """Copy every non-NULL secret from src_col to dst_col via `transform`.

    Used by both upgrade (encrypt) and downgrade (decrypt). Rows with a NULL
    source value are left untouched so an unconfigured secret stays NULL.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, {src_col} FROM {table} WHERE {src_col} IS NOT NULL")
    ).fetchall()
    for row_id, value in rows:
        bind.execute(
            sa.text(f"UPDATE {table} SET {dst_col} = :v WHERE id = :id"),
            {"v": transform(value), "id": row_id},
        )


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("shared_secret_encrypted", sa.Text(), nullable=True))
        # Data-migrate: encrypt each existing plaintext secret into the new column.
        _migrate_secrets(table, "shared_secret", "shared_secret_encrypted", encrypt_secret)
        op.drop_column(table, "shared_secret")


def downgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("shared_secret", sa.Text(), nullable=True))
        # Reverse: decrypt each ciphertext back to plaintext.
        _migrate_secrets(table, "shared_secret_encrypted", "shared_secret", decrypt_secret)
        op.drop_column(table, "shared_secret_encrypted")
