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

    def test_enhance_preview_prefers_deterministic_conversion_after_image_edit(self):
        class FakeUpload:
            content_type = "image/png"
            filename = "source.png"

            async def read(self):
                return b"fake image bytes"

        original_enhance = admin_router.enhance_image_for_beads
        original_convert = admin_router._convert_image_to_grid
        original_generate_grid = admin_router.generate_openai_bead_grid
        calls = {"convert": 0, "generate_grid": 0}

        try:
            admin_router.enhance_image_for_beads = lambda image_path, workdir: (
                f"{workdir}/ai_enhanced.png",
                {"attempted": True, "used": True, "provider": "openai"},
            )

            def fake_convert(image_path, grid_size, quality):
                calls["convert"] += 1
                self.assertTrue(image_path.endswith("ai_enhanced.png"))
                return {
                    "rows": 1,
                    "cols": 1,
                    "cells": [
                        {
                            "row": 1,
                            "col": 1,
                            "symbol": "A",
                            "color_hex": "#F47A8A",
                            "empty": False,
                        }
                    ],
                    "legend": [{"symbol": "A", "color_hex": "#F47A8A"}],
                    "artifacts": {},
                    "image": {"source_name": "ai_enhanced.png"},
                }

            def fake_generate_grid(*args, **kwargs):
                calls["generate_grid"] += 1
                raise AssertionError("OpenAI grid should not run when conversion succeeds")

            admin_router._convert_image_to_grid = fake_convert
            admin_router.generate_openai_bead_grid = fake_generate_grid

            result = asyncio.run(
                admin_router.enhance_preview(
                    file=FakeUpload(),
                    grid_size="52x52",
                    palette_name="MARD",
                    quality=85,
                    current_grid_json='{"rows":1,"cols":1}',
                    current_user=models.User(is_admin=True),
                )
            )

            self.assertEqual(calls, {"convert": 1, "generate_grid": 0})
            self.assertEqual(result["cells"][0]["symbol"], "A19")
            self.assertTrue(result["ai_enhancement"]["used"])
            self.assertFalse(result["ai_grid"]["attempted"])
            self.assertEqual(result["ai_grid"]["reason"], "deterministic_converter_used")
        finally:
            admin_router.enhance_image_for_beads = original_enhance
            admin_router._convert_image_to_grid = original_convert
            admin_router.generate_openai_bead_grid = original_generate_grid

    def test_enhance_preview_sends_original_image_and_grid_reference_to_openai_grid(self):
        class FakeUpload:
            content_type = "image/png"
            filename = "source.png"

            async def read(self):
                return b"fake image bytes"

        original_enhance = admin_router.enhance_image_for_beads
        original_convert = admin_router._convert_image_to_grid
        original_generate_grid = admin_router.generate_openai_bead_grid
        captured = {}

        try:
            def fake_enhance(image_path, workdir):
                return (
                    f"{workdir}/ai_enhanced.png",
                    {"attempted": True, "used": True, "provider": "openai"},
                )

            def fake_convert(image_path, grid_size, quality):
                raise ValueError("deterministic conversion failed")

            def fake_generate_grid(
                image_path,
                *,
                grid_size,
                quality,
                ai_metadata,
                current_grid_json=None,
                original_image_path=None,
            ):
                captured.update(
                    image_path=image_path,
                    current_grid_json=current_grid_json,
                    original_image_path=original_image_path,
                )
                result = normalize_openai_grid(
                    {
                        "rows": 1,
                        "cols": 1,
                        "palette": [{"id": "A", "name": "Pink", "hex": "#F47A8A"}],
                        "grid": [["A"]],
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

            admin_router.enhance_image_for_beads = fake_enhance
            admin_router._convert_image_to_grid = fake_convert
            admin_router.generate_openai_bead_grid = fake_generate_grid

            asyncio.run(
                admin_router.enhance_preview(
                    file=FakeUpload(),
                    grid_size="52x52",
                    palette_name="MARD",
                    quality=85,
                    current_grid_json='{"rows":1,"cols":1}',
                    current_user=models.User(is_admin=True),
                )
            )

            self.assertTrue(captured["image_path"].endswith("ai_enhanced.png"))
            self.assertTrue(captured["original_image_path"].endswith("source.png"))
            self.assertEqual(captured["current_grid_json"], '{"rows":1,"cols":1}')
        finally:
            admin_router.enhance_image_for_beads = original_enhance
            admin_router._convert_image_to_grid = original_convert
            admin_router.generate_openai_bead_grid = original_generate_grid

    def test_openai_prompts_use_beanbuddy_subject_extraction_constraints(self):
        from ai_enhancement import BEAD_IMAGE_ENHANCEMENT_PROMPT
        from openai_grid import OPENAI_GRID_PROMPT

        self.assertIn("Q-style", BEAD_IMAGE_ENHANCEMENT_PROMPT)
        self.assertIn("full subject contour", BEAD_IMAGE_ENHANCEMENT_PROMPT)
        self.assertIn("no shadows", BEAD_IMAGE_ENHANCEMENT_PROMPT)
        self.assertIn("original reference image", OPENAI_GRID_PROMPT)
        self.assertIn("remove isolated noisy beads", OPENAI_GRID_PROMPT.lower())


if __name__ == "__main__":
    unittest.main()
