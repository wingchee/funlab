import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

auth_stub = types.ModuleType("auth")
auth_stub.get_current_user = lambda: None
if "auth" in sys.modules:
    setattr(sys.modules["auth"], "get_current_user", lambda: None)
else:
    sys.modules["auth"] = auth_stub

import models  # noqa: E402
from routers import favorites, patterns  # noqa: E402


class GalleryPreviewDataTests(unittest.TestCase):
    def test_pattern_list_serialization_includes_grid_data_for_gallery_preview(self):
        pattern = models.Pattern(
            id=1,
            title="Checker",
            tags=json.dumps(["Test"]),
            size="Small",
            grid_w=2,
            grid_h=2,
            faves_count=0,
            preview_color="#F47A8A",
            palette=json.dumps([{"id": "A", "name": "Pink", "hex": "#F47A8A"}]),
            grid_data=json.dumps([["A", ""], ["", "A"]]),
        )

        payload = patterns._serialize(pattern)

        self.assertEqual(payload["grid_data"], [["A", ""], ["", "A"]])

    def test_favorite_serialization_includes_grid_data_for_gallery_preview(self):
        pattern = models.Pattern(
            id=1,
            title="Favorite Checker",
            tags=json.dumps(["Test"]),
            size="Small",
            grid_w=2,
            grid_h=2,
            faves_count=1,
            preview_color="#F47A8A",
            palette=json.dumps([{"id": "A", "name": "Pink", "hex": "#F47A8A"}]),
            grid_data=json.dumps([["A", ""], ["", "A"]]),
        )

        payload = favorites._serialize(pattern)

        self.assertEqual(payload["grid_data"], [["A", ""], ["", "A"]])

    def test_gallery_card_passes_grid_data_to_preview_canvas(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("gridData={pattern.grid_data}", html)
        self.assertIn("palette={pattern.palette}", html)
        self.assertIn("const paletteById = new Map", html)

    def test_gallery_preview_scales_full_grid_instead_of_cropping_to_first_cells(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("const drawRows = rows;", html)
        self.assertIn("const drawCols = cols;", html)
        self.assertNotIn("const drawRows = Math.min(rows, 28);", html)
        self.assertNotIn("const drawCols = Math.min(cols, 28);", html)

    def test_bead_viewer_opens_fullscreen_grid_in_new_tab(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("const openGridFullscreenTab = () =>", html)
        self.assertIn("fullscreenWindow.document.write", html)
        self.assertIn("data-action=\"zoom-in\"", html)
        self.assertIn("data-action=\"zoom-out\"", html)
        self.assertIn("let isDragging = false;", html)
        self.assertNotIn("requestFullscreen", html)
        self.assertLess(html.index("Fullscreen"), html.index("↓ Download PDF"))

    def test_bead_viewer_download_pdf_button_has_export_handler(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("const downloadPatternPdf = () =>", html)
        self.assertIn("pdfWindow.print();", html)
        self.assertIn("onClick={downloadPatternPdf}", html)
