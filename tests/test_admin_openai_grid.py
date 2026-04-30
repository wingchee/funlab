import asyncio
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

import models  # noqa: E402
import schemas  # noqa: E402
from database import Base  # noqa: E402
from openai_grid import normalize_openai_grid  # noqa: E402

auth_stub = types.ModuleType("auth")
auth_stub.get_admin_user = lambda: None
sys.modules.setdefault("auth", auth_stub)

import routers.admin as admin_router  # noqa: E402
from routers.admin import publish_pattern  # noqa: E402


class OpenAIGridTests(unittest.TestCase):
    def test_normalize_openai_grid_builds_processing_result(self):
        raw_grid = {
            "rows": 2,
            "cols": 3,
            "palette": [
                {"id": "A", "name": "Pink", "hex": "#F47A8A"},
                {"id": "B", "name": "Blue", "hex": "6BB5E8"},
            ],
            "grid": [
                ["A", "", "B"],
                ["B", "A", ""],
            ],
        }

        result = normalize_openai_grid(
            raw_grid,
            source_name="source.png",
            requested_size="52x52",
            ai_metadata={"attempted": True, "used": True, "provider": "openai"},
        )

        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["cols"], 3)
        self.assertEqual(
            result["legend"],
            [
                {
                    "symbol": "A",
                    "color_hex": "#F47A8A",
                    "confidence": 0.85,
                    "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
                    "name": "Pink",
                },
                {
                    "symbol": "B",
                    "color_hex": "#6BB5E8",
                    "confidence": 0.85,
                    "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
                    "name": "Blue",
                },
            ],
        )
        self.assertEqual(
            [(cell["row"], cell["col"], cell["symbol"], cell["empty"]) for cell in result["cells"]],
            [
                (1, 1, "A", False),
                (1, 2, "", True),
                (1, 3, "B", False),
                (2, 1, "B", False),
                (2, 2, "A", False),
                (2, 3, "", True),
            ],
        )
        self.assertEqual(result["image"], {"source_name": "source.png"})
        self.assertEqual(result["ai_enhancement"]["provider"], "openai")
        self.assertEqual(result["ai_grid"]["requested_size"], "52x52")

    def test_publish_pattern_persists_openai_grid_data(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            processing_result = normalize_openai_grid(
                {
                    "rows": 2,
                    "cols": 2,
                    "palette": [{"id": "P", "name": "Pink", "hex": "#F47A8A"}],
                    "grid": [["P", ""], ["", "P"]],
                },
                source_name="source.png",
                requested_size="52x52",
                ai_metadata={"attempted": True, "used": True, "provider": "openai"},
            )
            body = schemas.PublishRequest(
                title="AI Grid Pattern",
                tags=["AI"],
                size="Small",
                processing_result=processing_result,
            )

            response = publish_pattern(body, current_user=models.User(is_admin=True), db=db)
            saved = db.query(models.Pattern).filter(models.Pattern.id == response["id"]).one()

            self.assertEqual(saved.grid_w, 2)
            self.assertEqual(saved.grid_h, 2)
            self.assertEqual(json.loads(saved.grid_data), [["P", ""], ["", "P"]])
            self.assertEqual(json.loads(saved.palette), [{"id": "P", "name": "Pink", "hex": "#F47A8A"}])
        finally:
            db.close()

    def test_enhance_preview_uses_openai_grid_when_image_edit_is_rejected(self):
        class FakeUpload:
            content_type = "image/png"
            filename = "source.png"

            async def read(self):
                return b"fake image bytes"

        original_enhance = admin_router.enhance_image_for_beads
        original_generate_grid = admin_router.generate_openai_bead_grid

        try:
            admin_router.enhance_image_for_beads = lambda image_path, workdir: (
                image_path,
                {
                    "attempted": True,
                    "used": False,
                    "provider": "openai",
                    "error_type": "safety_blocked",
                    "reason": "OpenAI rejected this image edit request.",
                },
            )

            def fake_generate_grid(image_path, *, grid_size, quality, ai_metadata):
                result = normalize_openai_grid(
                    {
                        "rows": 1,
                        "cols": 2,
                        "palette": [{"id": "A", "name": "Pink", "hex": "#F47A8A"}],
                        "grid": [["A", ""]],
                    },
                    source_name="source.png",
                    requested_size=grid_size,
                    ai_metadata=ai_metadata,
                )
                result["ai_grid"] = {
                    "attempted": True,
                    "used": True,
                    "provider": "openai",
                    "requested_size": grid_size,
                }
                return result, result["ai_grid"]

            admin_router.generate_openai_bead_grid = fake_generate_grid

            result = asyncio.run(
                admin_router.enhance_preview(
                    file=FakeUpload(),
                    grid_size="52x52",
                    palette_name="MARD",
                    quality=85,
                    current_user=models.User(is_admin=True),
                )
            )

            self.assertEqual(result["rows"], 1)
            self.assertEqual(result["cols"], 2)
            self.assertEqual(result["cells"][0]["symbol"], "A19")
            self.assertTrue(result["ai_grid"]["used"])
            self.assertEqual(result["ai_enhancement"]["error_type"], "safety_blocked")
        finally:
            admin_router.enhance_image_for_beads = original_enhance
            admin_router.generate_openai_bead_grid = original_generate_grid


if __name__ == "__main__":
    unittest.main()
