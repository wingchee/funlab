import os
import sqlite3
import subprocess
import sys
import tempfile
import shutil
import textwrap
import unittest
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _columns(connection, table):
    return {row[1]: row for row in connection.execute(f"PRAGMA table_info('{table}')")}


def _foreign_keys(connection, table):
    return connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()


class MigrationTests(unittest.TestCase):
    def _upgrade(self, database_path: Path, revision: str = "head") -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{database_path}"})
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_upgrade_creates_unified_account_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "fresh.db"
            result = self._upgrade(database_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("users", tables)
                self.assertNotIn("members", tables)
                self.assertTrue({"member_packages", "member_visits"}.issubset(tables))
                user_columns = _columns(connection, "users")
                for name in (
                    "member_code",
                    "balance_access_token",
                    "phone",
                    "is_active",
                    "is_permanently_archived",
                    "notes",
                    "updated_at",
                ):
                    self.assertIn(name, user_columns)
                self.assertEqual(user_columns["member_code"][3], 0)
                self.assertEqual(user_columns["phone"][3], 0)
                for table, column in (
                    ("member_packages", "member_id"),
                    ("member_visits", "member_id"),
                    ("table_timers", "active_member_id"),
                    ("table_time_logs", "member_id"),
                ):
                    self.assertTrue(
                        any(
                            row[2] == "users" and row[3] == column
                            for row in _foreign_keys(connection, table)
                        )
                    )
                self.assertNotIn("member_id", _columns(connection, "favorites"))
                self.assertEqual(
                    connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                    "20260730_0005",
                )

    def test_upgrade_backfills_unique_balance_tokens_for_members_only(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "balance-tokens.db"
            prepared = self._upgrade(database_path, "20260711_0003")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.executemany(
                    "INSERT INTO users "
                    "(id, email, password_hash, name, is_admin, member_code, phone) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (1, "member@example.com", "hash", "Member", 0, "FL00000001", "60123456789"),
                        (2, "user@example.com", "hash", "User", 0, None, None),
                    ],
                )

            result = self._upgrade(database_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                member_token = connection.execute(
                    "SELECT balance_access_token FROM users WHERE id=1"
                ).fetchone()[0]
                non_member_token = connection.execute(
                    "SELECT balance_access_token FROM users WHERE id=2"
                ).fetchone()[0]

                self.assertIsInstance(member_token, str)
                self.assertGreaterEqual(len(member_token), 32)
                self.assertIsNone(non_member_token)
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE users SET balance_access_token=? WHERE id=2", (member_token,)
                    )

    def test_permanent_member_archive_migration_backfills_existing_users_on_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "permanent-member-archive.db"
            prepared = self._upgrade(database_path, "20260712_0004")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, name, is_admin) "
                    "VALUES (1, 'existing@example.com', 'hash', 'Existing', 0)"
                )

            result = self._upgrade(database_path, "20260730_0005")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                user_columns = _columns(connection, "users")
                self.assertEqual(user_columns["is_permanently_archived"][3], 1)
                self.assertIsNone(user_columns["is_permanently_archived"][4])
                self.assertEqual(
                    connection.execute(
                        "SELECT is_permanently_archived FROM users WHERE id=1"
                    ).fetchone()[0],
                    0,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE users SET is_permanently_archived=1, is_active=1, "
                        "phone='60123456003', balance_access_token='invalid' WHERE id=1"
                    )

    def test_upgrade_preserves_production_users_and_user_favorites(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "production.db"
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE users (
                        id INTEGER NOT NULL PRIMARY KEY,
                        email VARCHAR NOT NULL,
                        password_hash VARCHAR NOT NULL,
                        name VARCHAR NOT NULL,
                        is_admin BOOLEAN,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE UNIQUE INDEX ix_users_email ON users (email);
                    CREATE TABLE patterns (
                        id INTEGER NOT NULL PRIMARY KEY,
                        title VARCHAR NOT NULL,
                        tags TEXT NOT NULL,
                        size VARCHAR NOT NULL,
                        grid_w INTEGER NOT NULL,
                        grid_h INTEGER NOT NULL,
                        faves_count INTEGER,
                        preview_color VARCHAR NOT NULL,
                        palette TEXT NOT NULL,
                        grid_data TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE favorites (
                        id INTEGER NOT NULL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        pattern_id INTEGER NOT NULL REFERENCES patterns(id),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO users (id, email, password_hash, name, is_admin)
                    VALUES (7, ' Admin@Example.COM ', '$2b$12$preserved-hash', 'Admin', 1);
                    INSERT INTO patterns
                        (id, title, tags, size, grid_w, grid_h, faves_count,
                         preview_color, palette, grid_data)
                    VALUES (3, 'Pattern', '[]', 'Small', 1, 1, 1, '#fff', '[]', '[]');
                    INSERT INTO favorites (id, user_id, pattern_id) VALUES (9, 7, 3);
                    """
                )

            result = self._upgrade(database_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                expected = (7, " Admin@Example.COM ", "$2b$12$preserved-hash", "Admin", 1)
                actual = connection.execute(
                    "SELECT id, email, password_hash, name, is_admin FROM users WHERE id=7"
                ).fetchone()
                self.assertEqual(actual, expected)
                self.assertEqual(
                    connection.execute(
                        "SELECT user_id, pattern_id FROM favorites WHERE id=9"
                    ).fetchone(),
                    (7, 3),
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO users (email, password_hash, name, is_admin) "
                        "VALUES ('admin@example.com', 'hash', 'Duplicate', 0)"
                    )

    def test_upgrade_discards_experimental_member_rows_but_keeps_users(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "local-experimental.db"
            prepared = self._upgrade(database_path, "20260711_0002")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, name, is_admin) "
                    "VALUES (7, 'admin@example.com', '$2b$12$keep', 'Admin', 1)"
                )
                connection.execute(
                    "INSERT INTO patterns (id, title, tags, size, grid_w, grid_h, faves_count, "
                    "preview_color, palette, grid_data) "
                    "VALUES (3, 'Pattern', '[]', 'Small', 1, 1, 0, '#fff', '[]', '[]')"
                )
                connection.execute(
                    "INSERT INTO members (id, member_code, email, name, phone, is_active, notes) "
                    "VALUES (1, 'FL00000001', 'local@example.com', 'Local', '60111111111', 1, '')"
                )
                connection.execute(
                    "INSERT INTO member_packages "
                    "(id, member_id, package_name, total_seconds, remaining_seconds, notes) "
                    "VALUES (2, 1, 'Local', 3600, 3600, '')"
                )
                connection.execute(
                    "INSERT INTO table_time_logs "
                    "(id, table_number, member_id, started_at, ended_at, occupied_seconds, charged_seconds) "
                    "VALUES (4, 1, 1, '2026-01-01', '2026-01-01', 0, 0)"
                )
                connection.execute(
                    "INSERT INTO member_visits "
                    "(id, member_id, table_time_log_id, table_number, checked_in_at, checked_out_at, "
                    "occupied_seconds, charged_seconds, package_deducted_seconds, extra_due_seconds, notes) "
                    "VALUES (5, 1, 4, 1, '2026-01-01', '2026-01-01', 0, 0, 0, 0, '')"
                )
                connection.execute(
                    "UPDATE table_timers SET active_member_id=1 WHERE table_number=1"
                )

            result = self._upgrade(database_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertNotIn("members", tables)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM member_packages").fetchone()[0], 0
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM member_visits").fetchone()[0], 0
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT active_member_id FROM table_timers WHERE table_number=1"
                    ).fetchone()[0]
                )

    def test_raw_unstamped_malformed_legacy_members_do_not_block_head(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "raw-malformed.db"
            prepared = self._upgrade(database_path, "20260711_0002")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    DROP INDEX ix_members_phone;
                    DROP INDEX ix_members_email;
                    DROP INDEX ix_member_visits_table_time_log_id;
                    INSERT INTO users (id, email, password_hash, name, is_admin)
                    VALUES (7, ' Admin@Example.COM ', 'preserved-hash', 'Admin', 1);
                    INSERT INTO patterns
                        (id, title, tags, size, grid_w, grid_h, faves_count,
                         preview_color, palette, grid_data)
                    VALUES (3, 'Keep', '[]', 'Small', 1, 1, 1, '#fff', '[]', '[]');
                    INSERT INTO favorites (id, user_id, pattern_id) VALUES (9, 7, 3);
                    INSERT INTO members
                        (id, member_code, email, name, phone, is_active, notes)
                    VALUES
                        (1, 'FL00000001', ' DUP@example.com ', 'Broken One', '', 1, ''),
                        (2, 'FL00000002', 'dup@example.com', 'Broken Two', '', 1, '');
                    INSERT INTO member_packages
                        (id, member_id, package_name, total_seconds, remaining_seconds, notes)
                    VALUES (1, 1, 'Disposable', 3600, 3600, '');
                    INSERT INTO table_time_logs
                        (id, table_number, member_id, started_at, ended_at,
                         occupied_seconds, charged_seconds)
                    VALUES (4, 1, 1, '2026-01-01', '2026-01-01', 0, 0);
                    INSERT INTO member_visits
                        (id, member_id, table_time_log_id, table_number, checked_in_at,
                         checked_out_at, occupied_seconds, charged_seconds,
                         package_deducted_seconds, extra_due_seconds, notes)
                    VALUES
                        (5, 1, 4, 1, '2026-01-01', '2026-01-01', 0, 0, 0, 0, ''),
                        (6, 2, 4, 1, '2026-01-01', '2026-01-01', 0, 0, 0, 0, '');
                    DELETE FROM alembic_version;
                    """
                )

            result = self._upgrade(database_path)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT id, email, password_hash, name, is_admin FROM users"
                    ).fetchone(),
                    (7, " Admin@Example.COM ", "preserved-hash", "Admin", 1),
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT id, user_id, pattern_id FROM favorites"
                    ).fetchone(),
                    (9, 7, 3),
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM member_packages").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM member_visits").fetchone()[0], 0)
                self.assertFalse(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'"
                    ).fetchone()
                )

    def test_duplicate_normalized_user_emails_stop_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "duplicate-users.db"
            prepared = self._upgrade(database_path, "20260711_0002")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.executemany(
                    "INSERT INTO users (id, email, password_hash, name, is_admin) VALUES (?, ?, ?, ?, 0)",
                    [
                        (1, "same@example.com", "hash", "One"),
                        (2, " SAME@example.com ", "hash", "Two"),
                    ],
                )
            result = self._upgrade(database_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Duplicate normalized user emails", result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                self.assertNotIn("member_code", _columns(connection, "users"))
                self.assertEqual(
                    connection.execute("SELECT id, email FROM users ORDER BY id").fetchall(),
                    [(1, "same@example.com"), (2, " SAME@example.com ")],
                )

    def test_null_admin_permissions_abort_before_schema_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "null-admin.db"
            prepared = self._upgrade(database_path, "20260711_0002")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, name, is_admin) "
                    "VALUES (23, 'unclear@example.com', 'preserved-hash', 'Unclear', NULL)"
                )

            result = self._upgrade(database_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NULL is_admin values for user IDs: 23", result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                self.assertNotIn("member_code", _columns(connection, "users"))
                self.assertEqual(
                    connection.execute(
                        "SELECT id, email, password_hash, name, is_admin FROM users WHERE id=23"
                    ).fetchone(),
                    (23, "unclear@example.com", "preserved-hash", "Unclear", None),
                )

    def test_existing_non_unique_membership_indexes_are_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "wrong-indexes.db"
            prepared = self._upgrade(database_path, "20260711_0002")
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    ALTER TABLE users ADD COLUMN member_code VARCHAR;
                    ALTER TABLE users ADD COLUMN phone VARCHAR;
                    CREATE INDEX ix_users_member_code ON users (phone);
                    CREATE INDEX ix_users_phone ON users (phone);
                    """
                )

            result = self._upgrade(database_path)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                indexes = {
                    row[1]: row[2] for row in connection.execute("PRAGMA index_list('users')")
                }
                self.assertEqual(indexes["ix_users_member_code"], 1)
                self.assertEqual(indexes["ix_users_phone"], 1)
                self.assertEqual(
                    connection.execute("PRAGMA index_info('ix_users_member_code')").fetchone()[2],
                    "member_code",
                )
                self.assertEqual(
                    connection.execute("PRAGMA index_info('ix_users_phone')").fetchone()[2],
                    "phone",
                )

    def test_fk_check_aborts_before_orphan_revision_and_stamp_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            database_path = directory_path / "orphan-rollback.db"
            prepared = self._upgrade(database_path)
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "INSERT INTO users "
                    "(id, email, password_hash, name, is_admin, is_permanently_archived) "
                    "VALUES (7, 'keep@example.com', 'preserved-hash', 'Keep', 1, 0)"
                )

            migration_root = directory_path / "alembic"
            shutil.copytree(BACKEND / "alembic", migration_root)
            revision_path = migration_root / "versions" / "test_fk_orphan.py"
            revision_path.write_text(
                textwrap.dedent(
                    """\
                    from alembic import op
                    import sqlalchemy as sa

                    revision = "test_fk_orphan"
                    down_revision = "20260711_0003"
                    branch_labels = None
                    depends_on = None

                    def upgrade():
                        op.create_table(
                            "orphan_probe",
                            sa.Column("id", sa.Integer(), primary_key=True),
                            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
                        )
                        op.execute("INSERT INTO orphan_probe (id, user_id) VALUES (1, 999)")

                    def downgrade():
                        op.drop_table("orphan_probe")
                    """
                ),
                encoding="utf-8",
            )
            config_path = directory_path / "alembic.ini"
            config_path.write_text(
                (BACKEND / "alembic.ini").read_text(encoding="utf-8").replace(
                    "script_location = %(here)s/alembic",
                    f"script_location = {migration_root}",
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{database_path}"})

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    str(config_path),
                    "upgrade",
                    "test_fk_orphan",
                ],
                cwd=BACKEND,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Foreign key violations after Alembic migrations", result.stdout + result.stderr)
            with sqlite3.connect(database_path) as connection:
                self.assertEqual(
                    connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                    "20260730_0005",
                )
                self.assertFalse(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='orphan_probe'"
                    ).fetchone()
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT email, password_hash FROM users WHERE id=7"
                    ).fetchone(),
                    ("keep@example.com", "preserved-hash"),
                )

    def test_runtime_schema_mutation_is_removed_and_container_runs_migrations(self):
        self.assertNotIn("ensure_runtime_schema", (BACKEND / "database.py").read_text())
        self.assertNotIn("ensure_runtime_schema", (BACKEND / "main.py").read_text())
        self.assertIn(
            "alembic -c alembic.ini upgrade head", (BACKEND / "Dockerfile").read_text()
        )

    def test_local_database_is_ignored_and_quick_start_prepares_secret(self):
        gitignore = (ROOT / ".gitignore").read_text()
        deployment = (ROOT / "DEPLOYMENT.md").read_text()
        self.assertIn("backend/data/*.db", gitignore)
        quick_start = deployment.split("## Production Setup", 1)[0]
        self.assertIn("cp .env.example .env", quick_start)
        self.assertIn("secrets.token_hex(32)", quick_start)

    def test_migration_docs_preserve_existing_account_bytes_and_abort_on_ambiguity(self):
        design = (
            ROOT / "docs/superpowers/specs/2026-07-11-unified-account-table-design.md"
        ).read_text()
        plan = (
            ROOT / "docs/superpowers/plans/2026-07-11-unified-account-table.md"
        ).read_text()

        self.assertNotIn("Normalize existing user emails", design)
        self.assertNotIn('UPDATE users SET email=LOWER(TRIM(email))', plan)
        self.assertNotIn("UPDATE users SET is_admin=0 WHERE is_admin IS NULL", plan)
        self.assertIn("byte-for-byte", design)
        self.assertIn("NULL is_admin", design)


if __name__ == "__main__":
    unittest.main()
