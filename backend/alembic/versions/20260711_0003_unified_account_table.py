"""Consolidate all authenticated accounts into users.

Revision ID: 20260711_0003
Revises: 20260711_0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260711_0003"
down_revision: Union[str, None] = "20260711_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> dict[str, dict]:
    if table not in _tables():
        return {}
    return {
        index["name"]: index
        for index in sa.inspect(op.get_bind()).get_indexes(table)
        if index.get("name")
    }


def _drop_if_present(table: str) -> None:
    if table in _tables():
        op.drop_table(table)


def _foreign_keys(table: str) -> list[dict]:
    return sa.inspect(op.get_bind()).get_foreign_keys(table)


def _rebuild_timers_and_logs_with_user_fks() -> None:
    naming = {
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    }
    timer_fk = next(
        (
            key
            for key in _foreign_keys("table_timers")
            if key.get("constrained_columns") == ["active_member_id"]
        ),
        None,
    )
    with op.batch_alter_table(
        "table_timers", recreate="always", naming_convention=naming
    ) as batch:
        if timer_fk:
            batch.drop_constraint(
                timer_fk.get("name")
                or f"fk_table_timers_active_member_id_{timer_fk['referred_table']}",
                type_="foreignkey",
            )
        batch.create_foreign_key(
            "fk_table_timers_active_member_id_users",
            "users",
            ["active_member_id"],
            ["id"],
        )

    log_fk = next(
        (
            key
            for key in _foreign_keys("table_time_logs")
            if key.get("constrained_columns") == ["member_id"]
        ),
        None,
    )
    with op.batch_alter_table(
        "table_time_logs", recreate="always", naming_convention=naming
    ) as batch:
        if log_fk:
            batch.drop_constraint(
                log_fk.get("name")
                or f"fk_table_time_logs_member_id_{log_fk['referred_table']}",
                type_="foreignkey",
            )
        batch.create_foreign_key(
            "fk_table_time_logs_member_id_users",
            "users",
            ["member_id"],
            ["id"],
        )


def _replace_favorite_indexes() -> None:
    for name in list(_indexes("favorites")):
        if name in {
            "ix_favorites_member_id",
            "uq_favorites_member_pattern",
            "uq_favorites_user_pattern",
        }:
            op.drop_index(name, table_name="favorites")
    if "ix_favorites_user_id" not in _indexes("favorites"):
        op.create_index("ix_favorites_user_id", "favorites", ["user_id"])
    op.create_index(
        "uq_favorites_user_pattern",
        "favorites",
        ["user_id", "pattern_id"],
        unique=True,
    )


def _create_member_packages_referencing_users() -> None:
    op.create_table(
        "member_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("package_name", sa.String(), nullable=False),
        sa.Column("total_seconds", sa.Integer(), nullable=False),
        sa.Column("remaining_seconds", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("purchased_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_member_packages_member_id", "member_packages", ["member_id"])
    op.create_index("ix_member_packages_purchased_at", "member_packages", ["purchased_at"])


def _create_member_visits_referencing_users() -> None:
    op.create_table(
        "member_visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "table_time_log_id",
            sa.Integer(),
            sa.ForeignKey("table_time_logs.id"),
            nullable=True,
        ),
        sa.Column("table_number", sa.Integer(), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(), nullable=False),
        sa.Column("checked_out_at", sa.DateTime(), nullable=False),
        sa.Column("occupied_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("charged_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "package_deducted_seconds", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("extra_due_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_member_visits_member_id", "member_visits", ["member_id"])
    op.create_index(
        "ix_member_visits_table_time_log_id",
        "member_visits",
        ["table_time_log_id"],
        unique=True,
    )
    op.create_index("ix_member_visits_table_number", "member_visits", ["table_number"])
    op.create_index("ix_member_visits_checked_in_at", "member_visits", ["checked_in_at"])
    op.create_index("ix_member_visits_checked_out_at", "member_visits", ["checked_out_at"])


def _create_unique_user_membership_indexes() -> None:
    indexes = _indexes("users")
    if "ix_users_member_code" not in indexes:
        op.create_index("ix_users_member_code", "users", ["member_code"], unique=True)
    if "ix_users_phone" not in indexes:
        op.create_index("ix_users_phone", "users", ["phone"], unique=True)


def upgrade() -> None:
    connection = op.get_bind()
    user_columns = _columns("users")
    with op.batch_alter_table("users") as batch:
        if "member_code" not in user_columns:
            batch.add_column(sa.Column("member_code", sa.String(), nullable=True))
        if "phone" not in user_columns:
            batch.add_column(sa.Column("phone", sa.String(), nullable=True))
        if "is_active" not in user_columns:
            batch.add_column(
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
            )
        if "notes" not in user_columns:
            batch.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))
        if "updated_at" not in user_columns:
            batch.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )

    duplicates = connection.execute(
        sa.text(
            "SELECT LOWER(TRIM(email)) normalized_email FROM users "
            "GROUP BY LOWER(TRIM(email)) HAVING COUNT(*) > 1"
        )
    ).scalars().all()
    if duplicates:
        raise RuntimeError("Duplicate normalized user emails: " + ", ".join(duplicates))
    connection.execute(sa.text("UPDATE users SET email=LOWER(TRIM(email))"))
    connection.execute(sa.text("UPDATE users SET is_admin=0 WHERE is_admin IS NULL"))
    with op.batch_alter_table("users") as batch:
        batch.alter_column("is_admin", existing_type=sa.Boolean(), nullable=False)

    for table in ("member_visits", "member_packages"):
        _drop_if_present(table)

    connection.execute(
        sa.text(
            "UPDATE table_timers SET active_member_id=NULL, active_member_started_at=NULL"
        )
    )
    connection.execute(
        sa.text("UPDATE table_time_logs SET member_id=NULL, member_started_at=NULL")
    )
    _rebuild_timers_and_logs_with_user_fks()

    if "member_id" in _columns("favorites"):
        connection.execute(sa.text("DELETE FROM favorites WHERE user_id IS NULL"))
        for name in ("uq_favorites_member_pattern", "ix_favorites_member_id"):
            if name in _indexes("favorites"):
                op.drop_index(name, table_name="favorites")
        with op.batch_alter_table("favorites") as batch:
            batch.drop_column("member_id")
    if "user_id" in _columns("favorites"):
        with op.batch_alter_table("favorites") as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
    _replace_favorite_indexes()

    _drop_if_present("members")
    _create_member_packages_referencing_users()
    _create_member_visits_referencing_users()
    _create_unique_user_membership_indexes()


def downgrade() -> None:
    raise RuntimeError(
        "Unified account migration cannot be downgraded; restore the pre-migration SQLite backup"
    )
