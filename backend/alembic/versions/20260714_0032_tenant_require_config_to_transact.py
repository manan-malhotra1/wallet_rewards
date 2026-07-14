"""Add `require_config_to_transact` fail-closed flag to tenants (Epic 23).

When true, a money path (p2p, airtime, ...) may run only if BOTH a pricing
config and a limit config resolve for the acting user's type; otherwise the
service is rejected (`ServiceNotConfigured`, 422). Defaults false so existing
tenants keep today's fail-open behaviour until an operator opts in.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the boolean flag, NOT NULL with a false server default."""
    op.add_column(
        "tenants",
        sa.Column(
            "require_config_to_transact",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Drop the flag."""
    op.drop_column("tenants", "require_config_to_transact")
