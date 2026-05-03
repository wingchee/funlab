import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

auth_stub = types.ModuleType("auth")
auth_stub.get_admin_user = lambda: None
if "auth" in sys.modules:
    setattr(sys.modules["auth"], "get_admin_user", lambda: None)
else:
    sys.modules["auth"] = auth_stub

import models  # noqa: E402
import schemas  # noqa: E402
from routers import timetable  # noqa: E402


class TableTimerTests(unittest.TestCase):
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
        self.assertIn("Array.from({length: 8}", html)
        self.assertIn("page === 'timetable'", html)

    def test_frontend_table_query_renders_only_that_table(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("const isIndividualTablePage = selectedTable != null;", html)
        self.assertIn("const visibleTableSlots = isIndividualTablePage", html)
        self.assertIn("tableSlots.filter(table => table.table_number === selectedTable)", html)
        self.assertIn("visibleTableSlots.map(table =>", html)
        self.assertIn("Only Table", html)
