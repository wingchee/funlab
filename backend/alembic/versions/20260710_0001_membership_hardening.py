"""Create and harden the PixelCraft schema.

Revision ID: 20260710_0001
Revises: None
"""
from collections import Counter
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260710_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


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


def _create_index(
    name: str,
    table_name: str,
    columns: list[str],
    unique: bool = False,
) -> None:
    if name not in _index_map(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def _has_foreign_key(table_name: str, column_name: str, referred_table: str) -> bool:
    return any(
        foreign_key.get("constrained_columns") == [column_name]
        and foreign_key.get("referred_table") == referred_table
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def _create_core_tables() -> None:
    tables = _table_names()
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        _create_index("ix_users_email", "users", ["email"], unique=True)

    if "patterns" not in tables:
        op.create_table(
            "patterns",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("tags", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("size", sa.String(), nullable=False),
            sa.Column("grid_w", sa.Integer(), nullable=False),
            sa.Column("grid_h", sa.Integer(), nullable=False),
            sa.Column("faves_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("preview_color", sa.String(), nullable=False, server_default="#CC2936"),
            sa.Column("palette", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("grid_data", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    if "members" not in tables:
        op.create_table(
            "members",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("member_code", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("phone", sa.String(), nullable=False),
            sa.Column("password_hash", sa.String(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        _create_index("ix_members_member_code", "members", ["member_code"], unique=True)
        _create_index("ix_members_phone", "members", ["phone"], unique=True)

    tables = _table_names()
    if "table_timers" not in tables:
        op.create_table(
            "table_timers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("table_number", sa.Integer(), nullable=False),
            sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("elapsed_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("run_token", sa.String(), nullable=True),
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
            sa.Column("active_member_started_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        _create_index("ix_table_timers_table_number", "table_timers", ["table_number"], unique=True)
        _create_index("ix_table_timers_active_member_id", "table_timers", ["active_member_id"])

    if "table_time_logs" not in tables:
        op.create_table(
            "table_time_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("table_number", sa.Integer(), nullable=False),
            sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
            sa.Column("member_started_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=False),
            sa.Column("occupied_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("charged_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        _create_index("ix_table_time_logs_table_number", "table_time_logs", ["table_number"])
        _create_index("ix_table_time_logs_member_id", "table_time_logs", ["member_id"])
        _create_index("ix_table_time_logs_started_at", "table_time_logs", ["started_at"])
        _create_index("ix_table_time_logs_ended_at", "table_time_logs", ["ended_at"])

    tables = _table_names()
    if "favorites" not in tables:
        op.create_table(
            "favorites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("pattern_id", sa.Integer(), sa.ForeignKey("patterns.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    if "member_packages" not in tables:
        op.create_table(
            "member_packages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
            sa.Column("package_name", sa.String(), nullable=False),
            sa.Column("total_seconds", sa.Integer(), nullable=False),
            sa.Column("remaining_seconds", sa.Integer(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("purchased_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        _create_index("ix_member_packages_member_id", "member_packages", ["member_id"])
        _create_index("ix_member_packages_purchased_at", "member_packages", ["purchased_at"])

    if "member_visits" not in tables:
        op.create_table(
            "member_visits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
            sa.Column("table_time_log_id", sa.Integer(), sa.ForeignKey("table_time_logs.id"), nullable=True),
            sa.Column("table_number", sa.Integer(), nullable=False),
            sa.Column("checked_in_at", sa.DateTime(), nullable=False),
            sa.Column("checked_out_at", sa.DateTime(), nullable=False),
            sa.Column("occupied_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("charged_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("package_deducted_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("extra_due_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        _create_index("ix_member_visits_member_id", "member_visits", ["member_id"])
        _create_index(
            "ix_member_visits_table_time_log_id",
            "member_visits",
            ["table_time_log_id"],
            unique=True,
        )
        _create_index("ix_member_visits_table_number", "member_visits", ["table_number"])
        _create_index("ix_member_visits_checked_in_at", "member_visits", ["checked_in_at"])
        _create_index("ix_member_visits_checked_out_at", "member_visits", ["checked_out_at"])


def _upgrade_existing_timetable_tables() -> None:
    timer_columns = _column_names("table_timers")
    timer_needs_fk = not _has_foreign_key("table_timers", "active_member_id", "members")
    with op.batch_alter_table("table_timers") as batch:
        if "active_member_id" not in timer_columns:
            batch.add_column(sa.Column("active_member_id", sa.Integer(), nullable=True))
        if "active_member_started_at" not in timer_columns:
            batch.add_column(sa.Column("active_member_started_at", sa.DateTime(), nullable=True))
        if "run_token" not in timer_columns:
            batch.add_column(sa.Column("run_token", sa.String(), nullable=True))
        if "state_version" not in timer_columns:
            batch.add_column(
                sa.Column("state_version", sa.Integer(), nullable=False, server_default="0")
            )
        if timer_needs_fk:
            batch.create_foreign_key(
                "fk_table_timers_active_member_id_members",
                "members",
                ["active_member_id"],
                ["id"],
            )
    _create_index("ix_table_timers_active_member_id", "table_timers", ["active_member_id"])
    _create_index("ix_table_timers_table_number", "table_timers", ["table_number"], unique=True)

    log_columns = _column_names("table_time_logs")
    log_needs_fk = not _has_foreign_key("table_time_logs", "member_id", "members")
    with op.batch_alter_table("table_time_logs") as batch:
        if "member_id" not in log_columns:
            batch.add_column(sa.Column("member_id", sa.Integer(), nullable=True))
        if "member_started_at" not in log_columns:
            batch.add_column(sa.Column("member_started_at", sa.DateTime(), nullable=True))
        if log_needs_fk:
            batch.create_foreign_key(
                "fk_table_time_logs_member_id_members",
                "members",
                ["member_id"],
                ["id"],
            )
    _create_index("ix_table_time_logs_member_id", "table_time_logs", ["member_id"])
    _create_index("ix_table_time_logs_table_number", "table_time_logs", ["table_number"])
    _create_index("ix_table_time_logs_started_at", "table_time_logs", ["started_at"])
    _create_index("ix_table_time_logs_ended_at", "table_time_logs", ["ended_at"])


def _normalize_and_constrain_members() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, phone FROM members")).mappings().all()
    normalized_rows = [(row["id"], re.sub(r"\D", "", row["phone"] or "")) for row in rows]
    invalid_ids = [member_id for member_id, phone in normalized_rows if not phone]
    if invalid_ids:
        raise RuntimeError(f"Cannot migrate members with empty phone numbers: IDs {invalid_ids}")
    duplicates = sorted(
        phone for phone, count in Counter(phone for _, phone in normalized_rows).items() if count > 1
    )
    if duplicates:
        raise RuntimeError(
            "Cannot add unique member phones; resolve duplicate normalized values first: "
            + ", ".join(duplicates)
        )
    for member_id, phone in normalized_rows:
        connection.execute(
            sa.text("UPDATE members SET phone = :phone WHERE id = :member_id"),
            {"phone": phone, "member_id": member_id},
        )

    phone_index = _index_map("members").get("ix_members_phone")
    if phone_index and not phone_index.get("unique"):
        op.drop_index("ix_members_phone", table_name="members")
    _create_index("ix_members_phone", "members", ["phone"], unique=True)
    _create_index("ix_members_member_code", "members", ["member_code"], unique=True)


def _constrain_member_visits() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT table_time_log_id FROM member_visits "
            "WHERE table_time_log_id IS NOT NULL GROUP BY table_time_log_id HAVING COUNT(*) > 1"
        )
    ).scalars().all()
    if duplicates:
        raise RuntimeError(
            "Cannot make member visits idempotent; duplicate table_time_log_id values exist: "
            + ", ".join(str(value) for value in duplicates)
        )
    visit_index = _index_map("member_visits").get("ix_member_visits_table_time_log_id")
    if visit_index and not visit_index.get("unique"):
        op.drop_index("ix_member_visits_table_time_log_id", table_name="member_visits")
    _create_index(
        "ix_member_visits_table_time_log_id",
        "member_visits",
        ["table_time_log_id"],
        unique=True,
    )


def _seed_table_timers() -> None:
    connection = op.get_bind()
    existing = set(connection.execute(sa.text("SELECT table_number FROM table_timers")).scalars())
    missing = [number for number in range(1, 15) if number not in existing]
    if not missing:
        return
    table_timers = sa.table(
        "table_timers",
        sa.column("table_number", sa.Integer()),
        sa.column("is_running", sa.Boolean()),
        sa.column("elapsed_seconds", sa.Integer()),
        sa.column("state_version", sa.Integer()),
    )
    op.bulk_insert(
        table_timers,
        [
            {
                "table_number": number,
                "is_running": False,
                "elapsed_seconds": 0,
                "state_version": 0,
            }
            for number in missing
        ],
    )


def _is_raw_unstamped_legacy_schema(tables_before: set[str]) -> bool:
    if "members" not in tables_before or "alembic_version" not in _table_names():
        return False
    return op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM alembic_version")
    ).scalar_one() == 0


def upgrade() -> None:
    tables_before = _table_names()
    discard_legacy_members_at_unified_head = _is_raw_unstamped_legacy_schema(tables_before)
    if discard_legacy_members_at_unified_head:
        op.get_bind().info["discard_legacy_members_at_unified_head"] = True
    had_table_timers = "table_timers" in tables_before
    had_table_time_logs = "table_time_logs" in tables_before
    _create_core_tables()
    if had_table_timers or had_table_time_logs:
        _upgrade_existing_timetable_tables()
    if not discard_legacy_members_at_unified_head:
        _normalize_and_constrain_members()
        _constrain_member_visits()
    _seed_table_timers()


def downgrade() -> None:
    raise RuntimeError("This baseline-aware migration cannot be safely downgraded")
