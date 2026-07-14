"""Create admin_profiles — display-name cache for Keycloak admins (Epic 24).

Admins live in Keycloak; requests only carry the `sub`. This table caches each
admin's display name (recorded when they act) so admin surfaces render names,
never bare IDs. Not tenant-scoped — realm admins are cross-tenant operators.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the admin_profiles table (unique on keycloak_sub)."""
    op.create_table(
        "admin_profiles",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("keycloak_sub", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("keycloak_sub", name="uq_admin_profiles_keycloak_sub"),
    )


def downgrade() -> None:
    """Drop the admin_profiles table."""
    op.drop_table("admin_profiles")
