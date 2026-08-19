"""Tenant + created_at index for the audit log (Story B7.3).

The admin audit page's default view is `WHERE tenant_id ORDER BY created_at
DESC LIMIT/OFFSET`, but audit_log only had entity- and actor-keyed indexes —
so every unfiltered page load seq-scanned and top-N sorted a table that grows
for 7 years (immutable, no purge job).

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the tenant-scoped newest-first index the audit page reads through."""
    op.create_index(
        "ix_audit_log_tenant_created", "audit_log", ["tenant_id", "created_at"], unique=False
    )


def downgrade() -> None:
    """Drop the audit page index."""
    op.drop_index("ix_audit_log_tenant_created", table_name="audit_log")
