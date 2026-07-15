"""allow 'update' operation on config_change_requests (maker-checker edit).

Adds the third maker-checker operation. Today `config_change_requests.operation`
permits only 'create'/'delete'; a create 409s on an existing scope, so a live
config cannot be edited. Widen the CHECK constraint to also allow 'update'
(drop + recreate — reversible).

Revision ID: 0038
Revises: 0037
Create Date: 2026-07-15
"""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_config_change_requests_operation"
_TABLE = "config_change_requests"


def upgrade() -> None:
    """Swap the operation CHECK to also allow 'update'."""
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "operation IN ('create', 'update', 'delete')",
    )


def downgrade() -> None:
    """Restore the create/delete-only CHECK (reversible)."""
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "operation IN ('create', 'delete')",
    )
