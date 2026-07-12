import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import models  # noqa: E402
from routers import auth as auth_router  # noqa: E402
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

    def test_public_registration_uses_canonical_auth_router(self):
        self.assertTrue(callable(auth_router.register))

    def test_admin_gallery_delete_has_confirmation_and_reload_hook(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("function PatternCard({ pattern, onOpen, isFaved, onFave, isLoggedIn, isAdmin, onDelete })", html)
        self.assertIn("window.confirm(`Delete ${pattern.title}? This cannot be undone.`)", html)
        self.assertIn("apiFetch(`/patterns/${id}`", html)
        self.assertIn("method: 'DELETE'", html)
        self.assertIn("onPatternDeleted={onDeletePattern}", html)

    def test_pdf_download_is_visible_to_admin_only(self):
        html = (ROOT / "frontend" / "index.html").read_text()

        self.assertIn("const isAdmin = !!user?.is_admin;", html)
        self.assertIn("{isAdmin && (", html)
        self.assertLess(html.index("{isAdmin && ("), html.index("↓ Download PDF"))
