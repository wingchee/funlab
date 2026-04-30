# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PixelCraft (拼豆)** — a web platform for Perler/Hama pixel bead art enthusiasts. The repository contains three components:

1. **`design_handoff_pindou/`** — High-fidelity interactive prototype (React/Babel in a single HTML file). This is a *design reference only*, not production code. Implement from it in your target framework.
2. **`grid recovery python/`** — Python image-to-bead-grid converter. Two layers:
   - Standalone scripts (`grid_recovery.py`, `grid_web_export.py`) — run directly for dev/testing.
   - `services/processor/` — FastAPI microservice wrapping those scripts.
3. **`PixelCraft_PRD.md`** — Product Requirements Document.

---

## Running the Python Scripts

### Standalone (dev/testing)

```bash
cd "grid recovery python"
python grid_recovery.py   # expects blur.JPG in the same directory; writes outputs/ subdirectories
```

### FastAPI Microservice

```bash
cd "grid recovery python/services/processor"
uvicorn app:app --reload
```

Endpoints:
- `GET /health`
- `POST /process` — body: `{ "image_path": "..." }` or `{ "image_url": "..." }`. Optionally set `PROCESSOR_SHARED_SECRET` env var; if set, requests must include `X-Internal-Token` header.

---

## Architecture

### Image Processing Pipeline (`grid_recovery.py`)

The pipeline runs in this order for a given input image:

1. **`detect_grid_layout(image)`** — Uses morphological OpenCV operations to find horizontal/vertical grid lines and compute a `GridLayout` (bounding box, cell size, row/col count, line positions).
2. **`extract_legend_entries(image, layout)`** — Two strategies tried in order:
   - *Structured footer* (`_extract_structured_footer_entries`) — detects colored swatch blocks below the grid, infers slot positions, OCRs labels.
   - *Fallback* — HSV-based swatch detection + Tesseract OCR on text strips below the grid.
3. **`_extract_cells`** — Crops each cell, computes dominant color, flags near-white cells as empty.
4. **`_cluster_cells`** — k-means on BGR colors to group cells into up to 14 clusters.
5. **`_seed_ocr_for_clusters`** — Runs Tesseract OCR on a representative sample of cells per cluster (center-biased) to seed symbol candidates.
6. **Symbol assignment** — Three output variants are generated (`approach_1/2/3`):
   - Approach 1: raw OCR per-cell, no consensus.
   - Approach 2: color-distance matching against the detected legend (`assign_cells_from_legend`).
   - Approach 3: Approach 2 + `smooth_high_risk_regions` (neighbor-voting correction for border/contour cells) + review flags.
7. **Output** — Each approach writes `preview.png` + `grid.csv`; approach_2 also writes `legend.csv`.

`generate_web_result` calls the full pipeline and returns a JSON-ready payload via `build_web_export_payload` (reads approach_3 CSV for cells, approach_2 for legend).

### Microservice (`services/processor/`)

`app.py` (FastAPI) → `processor_service.py` → `web_export.py` → `_repo_imports.load_repo_module("grid_recovery")`.

`_repo_imports.py` dynamically loads `grid_recovery.py` from the repo root (`services/processor/../../`) at runtime, so the service always uses the repo's copy of the script without installing it as a package.

### Design Prototype (`design_handoff_pindou/PixelCraft.html`)

Single-file React SPA (CDN React + Babel). All five screens are included. State persisted to `localStorage` keys: `pc_page`, `pc_favs`, `pc_loggedin`, `pc_admin`. The bead map grid is generated from a deterministic sine-wave formula — replace with real backend data. Auth is simulated (email containing "admin" → admin role).

---

## Design Tokens (implement pixel-accurately)

| Token | Value | Usage |
|---|---|---|
| Primary | `#F47A8A` | CTA buttons, active nav, accents |
| Secondary | `#6BB5E8` | Gradients, secondary actions |
| BG | `#FEF4F5` | Page background |
| Surface | `#FFFFFF` | Cards, modals |
| Border | `#E8E6E1` | Card/input borders |
| Primary gradient | `linear-gradient(135deg, #F47A8A, #6BB5E8)` | CTAs, avatar, progress bar fill |

**Fonts:** `Space Grotesk` (400/500/600/700) for all UI text; `Space Mono` (400/700) for counts/codes/size badges. Load from Google Fonts.

**Pixel grid background:** CSS `background-image` with two `linear-gradient` lines at 4% opacity, `24px` background-size (see `.pixel-bg` class in the prototype).

---

## Dependencies

Python requirements (not in a requirements file yet):
- `opencv-python` (`cv2`)
- `numpy`
- `Pillow`
- `pytesseract` (requires Tesseract binary installed)
- `fastapi`, `uvicorn`, `pydantic` (microservice only)

Font path for preview rendering is hardcoded to macOS: `/System/Library/Fonts/Supplemental/Arial Unicode.ttf` — falls back to PIL default if missing.
