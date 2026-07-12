import json
import os
import sys
import unittest
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
from color_systems import COLOR_SYSTEMS, _indexed_colors, apply_color_system_to_result, nearest_bead_color  # noqa: E402
from database import Base  # noqa: E402
from routers.admin import publish_pattern  # noqa: E402


class ColorSystemsTests(unittest.TestCase):
    def test_only_mard_221_palette_is_available(self):
        self.assertEqual(COLOR_SYSTEMS, ("MARD",))
        self.assertEqual(len(_indexed_colors()), 221)

        bead = nearest_bead_color("#FBF4EC", "COCO")

        self.assertEqual(bead, {"id": "E16", "name": "E16", "hex": "#FBF4EC"})

    def test_nearest_bead_color_returns_mard_code(self):
        exact = nearest_bead_color("#FAF4C8", "MARD")
        near = nearest_bead_color("#FAF4C9", "COCO")

        self.assertEqual(exact, {"id": "A1", "name": "A1", "hex": "#FAF5CD"})
        self.assertEqual(near, {"id": "A1", "name": "A1", "hex": "#FAF5CD"})

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

        self.assertEqual([entry["symbol"] for entry in mapped["legend"]], ["A1", "A2"])
        self.assertEqual([entry["color_hex"] for entry in mapped["legend"]], ["#FAF5CD", "#FCFED6"])
        self.assertEqual([cell["symbol"] for cell in mapped["cells"]], ["A1", "A2", ""])
        self.assertEqual(mapped["palette_name"], "MARD")

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

            self.assertEqual(json.loads(saved.grid_data), [["A1", ""]])
            self.assertEqual(json.loads(saved.palette), [{"id": "A1", "name": "A1", "hex": "#FAF5CD"}])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
