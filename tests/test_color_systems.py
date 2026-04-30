import json
import sys
import types
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

auth_stub = types.ModuleType("auth")
auth_stub.get_admin_user = lambda: None
sys.modules.setdefault("auth", auth_stub)

import models  # noqa: E402
import schemas  # noqa: E402
from color_systems import apply_color_system_to_result, nearest_bead_color  # noqa: E402
from database import Base  # noqa: E402
from routers.admin import publish_pattern  # noqa: E402


class ColorSystemsTests(unittest.TestCase):
    def test_nearest_bead_color_returns_selected_system_code(self):
        exact = nearest_bead_color("#FAF4C8", "MARD")
        near = nearest_bead_color("#FAF4C9", "COCO")

        self.assertEqual(exact, {"id": "A01", "name": "A01", "hex": "#FAF4C8"})
        self.assertEqual(near, {"id": "E02", "name": "E02", "hex": "#FAF4C8"})

    def test_apply_color_system_rewrites_cells_and_legend(self):
        result = {
            "rows": 1,
            "cols": 3,
            "legend": [
                {"symbol": "A", "color_hex": "#FAF4C8"},
                {"symbol": "B", "color_hex": "#FFFFD5"},
            ],
            "cells": [
                {"row": 1, "col": 1, "symbol": "A", "color_hex": "#FAF4C8", "empty": False},
                {"row": 1, "col": 2, "symbol": "B", "color_hex": "#FFFFD5", "empty": False},
                {"row": 1, "col": 3, "symbol": "", "color_hex": "#FFFFFF", "empty": True},
            ],
        }

        mapped = apply_color_system_to_result(result, "盼盼")

        self.assertEqual([entry["symbol"] for entry in mapped["legend"]], ["65", "2"])
        self.assertEqual([entry["color_hex"] for entry in mapped["legend"]], ["#FAF4C8", "#FFFFD5"])
        self.assertEqual([cell["symbol"] for cell in mapped["cells"]], ["65", "2", ""])
        self.assertEqual(mapped["palette_name"], "盼盼")

    def test_publish_pattern_persists_selected_system_codes(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            mapped = apply_color_system_to_result(
                {
                    "rows": 1,
                    "cols": 2,
                    "legend": [
                        {"symbol": "A", "color_hex": "#FAF4C8"},
                    ],
                    "cells": [
                        {"row": 1, "col": 1, "symbol": "A", "color_hex": "#FAF4C8", "empty": False},
                        {"row": 1, "col": 2, "symbol": "", "color_hex": "#FFFFFF", "empty": True},
                    ],
                },
                "咪小窝",
            )
            body = schemas.PublishRequest(
                title="Mapped Pattern",
                tags=["色号"],
                size="Small",
                processing_result=mapped,
            )

            response = publish_pattern(body, current_user=models.User(is_admin=True), db=db)
            saved = db.query(models.Pattern).filter(models.Pattern.id == response["id"]).one()

            self.assertEqual(json.loads(saved.grid_data), [["77", ""]])
            self.assertEqual(json.loads(saved.palette), [{"id": "77", "name": "77", "hex": "#FAF4C8"}])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
