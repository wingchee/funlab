import sys
import os
import unittest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import models  # noqa: E402
import schemas  # noqa: E402
from routers import timetable  # noqa: E402


class TableTimerTests(unittest.TestCase):
    def _session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        models.Base.metadata.create_all(bind=engine)
        return sessionmaker(bind=engine)()

    def test_stopped_table_serializes_as_free_with_existing_elapsed_time(self):
        timer = models.TableTimer(
            id=1,
            table_number=3,
            is_running=False,
            elapsed_seconds=900,
            started_at=None,
        )

        payload = timetable._serialize(timer, now=datetime(2026, 5, 3, 12, 0, 0))

        self.assertEqual(payload["table_number"], 3)
        self.assertEqual(payload["status"], "Free")
        self.assertFalse(payload["is_running"])
        self.assertEqual(payload["elapsed_seconds"], 900)

    def test_running_table_serializes_as_occupied_and_adds_live_elapsed_time(self):
        now = datetime(2026, 5, 3, 12, 0, 0)
        timer = models.TableTimer(
            id=2,
            table_number=7,
            is_running=True,
            elapsed_seconds=120,
            started_at=now - timedelta(seconds=45),
        )

        payload = timetable._serialize(timer, now=now)

        self.assertEqual(payload["status"], "Occupied")
        self.assertTrue(payload["is_running"])
        self.assertEqual(payload["elapsed_seconds"], 165)

    def test_admin_set_request_accepts_elapsed_seconds(self):
        body = schemas.TableTimerSetRequest(elapsed_seconds=3600, is_running=True)

        self.assertEqual(body.elapsed_seconds, 3600)
        self.assertTrue(body.is_running)

    def test_frontend_adds_time_table_nav_page_and_table_links(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("['timetable','Time Table']", html)
        self.assertIn("function TimeTablePage", html)
        self.assertIn("apiFetch('/timetable')", html)
        self.assertIn("copyTableLink", html)
        self.assertIn("Array.from({length: 14}", html)
        self.assertIn("page === 'timetable'", html)

    def test_backend_creates_fourteen_table_timers(self):
        db = self._session()

        timetable._ensure_table_timers(db)

        rows = db.query(models.TableTimer).order_by(models.TableTimer.table_number.asc()).all()
        self.assertEqual([row.table_number for row in rows], list(range(1, 15)))

    def test_duplicate_timer_seed_attempts_are_conflict_safe_on_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'timer-seed.db'}",
                connect_args={"check_same_thread": False},
            )
            models.Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)
            first_db = Session()
            second_db = Session()
            table_numbers = list(range(1, 15))

            timetable._insert_missing_table_timers(first_db, table_numbers)
            timetable._insert_missing_table_timers(second_db, table_numbers)

            rows = second_db.query(models.TableTimer.table_number).all()
            self.assertEqual(sorted(row.table_number for row in rows), table_numbers)
            first_db.close()
            second_db.close()

    def test_reset_all_query_locks_every_timer_before_settlement(self):
        db = self._session()
        timetable._ensure_table_timers(db)

        query = timetable._all_timers_for_update(db)

        self.assertIsNotNone(query._for_update_arg)
        self.assertIn("table_number", str(query._order_by_clauses[0]))

    def test_table_fifteen_is_not_available(self):
        db = self._session()

        with self.assertRaises(Exception) as raised:
            timetable._get_table(db, 15)

        self.assertEqual(getattr(raised.exception, "status_code", None), 404)

    def test_frontend_table_query_renders_only_that_table(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("const isIndividualTablePage = selectedTable != null;", html)
        self.assertIn("const visibleTableSlots = isIndividualTablePage", html)
        self.assertIn("tableSlots.filter(table => table.table_number === selectedTable)", html)
        self.assertIn("visibleTableSlots.map(table =>", html)
        self.assertIn("Only Table", html)
        self.assertIn("number >= 1 && number <= 14 ? number : null", html)

    def test_frontend_occupied_count_uses_fourteen_tables(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("{occupiedCount}/14", html)

    def test_reset_all_tables_clears_every_timer_and_logs_running_tables(self):
        reset_all = getattr(timetable, "reset_all_tables", None)
        self.assertIsNotNone(reset_all, "timetable.reset_all_tables should exist")
        db = self._session()
        now = datetime(2026, 5, 3, 12, 0, 0)
        db.add_all([
            models.TableTimer(
                table_number=1,
                is_running=True,
                elapsed_seconds=120,
                started_at=now - timedelta(seconds=300),
            ),
            models.TableTimer(
                table_number=2,
                is_running=False,
                elapsed_seconds=900,
                started_at=None,
            ),
        ])
        db.commit()

        payload = reset_all(_=None, db=db, now=now)

        rows = db.query(models.TableTimer).order_by(models.TableTimer.table_number.asc()).all()
        self.assertEqual([row.table_number for row in rows], list(range(1, 15)))
        self.assertTrue(all(not row.is_running for row in rows))
        self.assertTrue(all(row.elapsed_seconds == 0 for row in rows))
        self.assertTrue(all(row.started_at is None for row in rows))
        self.assertEqual(len(payload), 14)

        logs = db.query(models.TableTimeLog).all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].table_number, 1)
        self.assertEqual(logs[0].occupied_seconds, 300)

    def test_charge_seconds_rounds_by_first_hour_then_half_hour_grace(self):
        calculator = getattr(timetable, "calculate_charged_seconds", None)
        self.assertIsNotNone(calculator, "timetable.calculate_charged_seconds should exist")

        self.assertEqual(calculator(0), 0)
        self.assertEqual(calculator(1), 3600)
        self.assertEqual(calculator(3600), 3600)
        self.assertEqual(calculator(4200), 3600)
        self.assertEqual(calculator(4201), 5400)
        self.assertEqual(calculator(6000), 5400)
        self.assertEqual(calculator(6001), 7200)

    def test_stop_table_persists_completed_time_log_with_charged_seconds(self):
        self.assertTrue(hasattr(models, "TableTimeLog"), "models.TableTimeLog should exist")
        db = self._session()
        now = datetime(2026, 5, 3, 12, 0, 0)
        timer = models.TableTimer(
            table_number=1,
            is_running=True,
            elapsed_seconds=0,
            started_at=now - timedelta(seconds=4201),
        )
        db.add(timer)
        db.commit()

        timetable.stop_table(1, _=None, db=db, now=now)

        logs = db.query(models.TableTimeLog).all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].table_number, 1)
        self.assertEqual(logs[0].occupied_seconds, 4201)
        self.assertEqual(logs[0].charged_seconds, 5400)

    def test_daily_report_summarizes_logs_for_requested_day(self):
        self.assertTrue(hasattr(models, "TableTimeLog"), "models.TableTimeLog should exist")
        reporter = getattr(timetable, "get_report", None)
        self.assertIsNotNone(reporter, "timetable.get_report should exist")
        db = self._session()
        db.add_all([
            models.TableTimeLog(
                table_number=1,
                started_at=datetime(2026, 5, 3, 10, 0, 0),
                ended_at=datetime(2026, 5, 3, 11, 10, 1),
                occupied_seconds=4201,
                charged_seconds=5400,
            ),
            models.TableTimeLog(
                table_number=2,
                started_at=datetime(2026, 5, 3, 12, 0, 0),
                ended_at=datetime(2026, 5, 3, 12, 30, 0),
                occupied_seconds=1800,
                charged_seconds=3600,
            ),
            models.TableTimeLog(
                table_number=1,
                started_at=datetime(2026, 5, 4, 10, 0, 0),
                ended_at=datetime(2026, 5, 4, 10, 30, 0),
                occupied_seconds=1800,
                charged_seconds=3600,
            ),
        ])
        db.commit()

        report = reporter(date="2026-05-03", db=db)

        self.assertEqual(report["date"], "2026-05-03")
        self.assertEqual(report["summary"]["sessions"], 2)
        self.assertEqual(report["summary"]["occupied_seconds"], 6001)
        self.assertEqual(report["summary"]["charged_seconds"], 9000)
        self.assertEqual(len(report["logs"]), 2)
        self.assertEqual(report["daily_report"][0]["table_number"], 1)
        self.assertEqual(report["daily_report"][0]["occupied_seconds"], 4201)

    def test_frontend_renders_time_log_and_daily_report_sections(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("loadReport", html)
        self.assertIn("apiFetch(`/timetable/report?date=${reportDate}`)", html)
        self.assertIn("Time Log", html)
        self.assertIn("Charging Time", html)
        self.assertIn("Daily Report", html)

    def test_frontend_confirms_before_resetting_table_timer(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("window.confirm(`Reset Table #${tableNumber} timer?", html)
        self.assertIn("if (action === 'reset'", html)

    def test_frontend_confirms_before_resetting_all_table_timers(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("function resetAllTables", html)
        self.assertIn("window.confirm('Reset all table timers?", html)
        self.assertIn("apiFetch('/timetable/reset-all', { method: 'POST' })", html)
        self.assertIn("Reset All Timers", html)
