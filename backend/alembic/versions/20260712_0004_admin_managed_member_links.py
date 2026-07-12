"""Add private balance access tokens for member accounts.

Revision ID: 20260712_0004
Revises: 20260711_0003
"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_0004"
down_revision: Union[str, None] = "20260711_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _next_unique_balance_access_token(connection) -> str:
    while True:
        token = secrets.token_urlsafe(32)
        exists = connection.execute(
            sa.text("SELECT 1 FROM users WHERE balance_access_token=:token"),
            {"token": token},
        ).scalar()
        if exists is None:
            return token


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("balance_access_token", sa.String(), nullable=True)
    )
    op.create_index(
        "ix_users_balance_access_token",
        "users",
        ["balance_access_token"],
        unique=True,
    )

    connection = op.get_bind()
    member_ids = connection.execute(
        sa.text(
            "SELECT id FROM users "
            "WHERE member_code IS NOT NULL AND balance_access_token IS NULL"
        )
    ).scalars()
    for member_id in member_ids:
        connection.execute(
            sa.text(
                "UPDATE users SET balance_access_token=:token WHERE id=:member_id"
            ),
            {"token": _next_unique_balance_access_token(connection), "member_id": member_id},
        )


def downgrade() -> None:
    op.drop_index("ix_users_balance_access_token", table_name="users")
    op.drop_column("users", "balance_access_token")
