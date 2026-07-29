"""Persist permanent member archive state.

Revision ID: 20260730_0005
Revises: 20260712_0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0005"
down_revision: Union[str, None] = "20260712_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_permanently_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "is_permanently_archived",
            existing_type=sa.Boolean(),
            server_default=None,
        )


def downgrade() -> None:
    op.drop_column("users", "is_permanently_archived")
