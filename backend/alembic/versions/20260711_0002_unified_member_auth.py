"""Add member email and member-owned favorites.

Revision ID: 20260711_0002
Revises: 20260710_0001
"""
from collections import Counter
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260711_0002"
down_revision: Union[str, None] = "20260710_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_map(table_name: str) -> dict[str, dict]:
    return {
        index["name"]: index
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def _normalize_existing_emails() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, email FROM members WHERE email IS NOT NULL")
    ).mappings().all()
    normalized = [
        (row["id"], (row["email"] or "").strip().lower())
        for row in rows
    ]
    duplicates = sorted(
        email
        for email, count in Counter(email for _, email in normalized if email).items()
        if count > 1
    )
    if duplicates:
        raise RuntimeError(
            "Cannot add unique member emails; resolve duplicate normalized values first: "
            + ", ".join(duplicates)
        )
    for member_id, email in normalized:
        connection.execute(
            sa.text("UPDATE members SET email = :email WHERE id = :member_id"),
            {"email": email or None, "member_id": member_id},
        )


def upgrade() -> None:
    discard_legacy_members = bool(
        op.get_bind().info.get("discard_legacy_members_at_unified_head")
    )
    if "email" not in _column_names("members"):
        op.add_column("members", sa.Column("email", sa.String(), nullable=True))
    if not discard_legacy_members:
        _normalize_existing_emails()
    if not discard_legacy_members and "ix_members_email" not in _index_map("members"):
        op.create_index("ix_members_email", "members", ["email"], unique=True)

    favorite_columns = _column_names("favorites")
    with op.batch_alter_table("favorites") as batch:
        if "member_id" not in favorite_columns:
            batch.add_column(sa.Column("member_id", sa.Integer(), nullable=True))
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
        if "member_id" not in favorite_columns:
            batch.create_foreign_key(
                "fk_favorites_member_id_members",
                "members",
                ["member_id"],
                ["id"],
            )

    favorite_indexes = _index_map("favorites")
    if "ix_favorites_member_id" not in favorite_indexes:
        op.create_index("ix_favorites_member_id", "favorites", ["member_id"])
    if "uq_favorites_member_pattern" not in favorite_indexes:
        op.create_index(
            "uq_favorites_member_pattern",
            "favorites",
            ["member_id", "pattern_id"],
            unique=True,
        )


def downgrade() -> None:
    member_favorites = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM favorites WHERE member_id IS NOT NULL")
    ).scalar_one()
    if member_favorites:
        raise RuntimeError("Cannot downgrade while member-owned favorites exist")

    favorite_indexes = _index_map("favorites")
    if "uq_favorites_member_pattern" in favorite_indexes:
        op.drop_index("uq_favorites_member_pattern", table_name="favorites")
    if "ix_favorites_member_id" in favorite_indexes:
        op.drop_index("ix_favorites_member_id", table_name="favorites")
    with op.batch_alter_table("favorites") as batch:
        batch.drop_constraint("fk_favorites_member_id_members", type_="foreignkey")
        batch.drop_column("member_id")
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)

    if "ix_members_email" in _index_map("members"):
        op.drop_index("ix_members_email", table_name="members")
    with op.batch_alter_table("members") as batch:
        batch.drop_column("email")
