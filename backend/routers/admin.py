import csv
import io
import json
import os
import tempfile
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from ai_enhancement import enhance_image_for_beads
from auth import get_admin_user
from color_systems import COLOR_SYSTEMS, apply_color_system_to_result
from database import get_db
from openai_grid import generate_openai_bead_grid

router = APIRouter()

_PHOTO_SIZES = ["52x52", "78x78", "104x104"]
_CSV_CONTENT_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"}


def _validate_palette_name(palette_name: str) -> str:
    if palette_name not in COLOR_SYSTEMS:
        raise HTTPException(status_code=400, detail=f"palette_name must be one of {', '.join(COLOR_SYSTEMS)}")
    return palette_name


def _is_ai_image_edit_rejected(ai_enhancement: dict) -> bool:
    return ai_enhancement.get("error_type") == "safety_blocked"


def _is_csv_upload(file: UploadFile) -> bool:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    return filename.endswith(".csv") or content_type in _CSV_CONTENT_TYPES


def _decode_csv_upload(contents: bytes) -> str:
    try:
        return contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contents.decode("latin-1")


def _csv_to_processing_result(contents: bytes, source_name: str) -> dict:
    text = _decode_csv_upload(contents)
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if not rows:
        raise ValueError("CSV file is empty")

    cols = len(rows[0])
    if cols == 0:
        raise ValueError("CSV file has no columns")

    cells = []
    legend = []
    symbol_by_hex: dict[str, str] = {}

    for row_idx, row in enumerate(rows, start=1):
        if len(row) != cols:
            raise ValueError(f"Row {row_idx} has {len(row)} columns; expected {cols}")

        for col_idx, raw_value in enumerate(row, start=1):
            value = str(raw_value or "").strip()
            empty = value == "" or value.upper() in {"TRANSPARENT", "EMPTY", "NONE", "NULL"}
            if empty:
                cells.append({
                    "row": row_idx,
                    "col": col_idx,
                    "symbol": "",
                    "color_hex": "#FFFFFF",
                    "empty": True,
                })
                continue

            color_hex = value.upper()
            if not color_hex.startswith("#"):
                color_hex = f"#{color_hex}"
            if len(color_hex) != 7:
                raise ValueError(f"Row {row_idx}, column {col_idx} has invalid color value: {value}")
            try:
                int(color_hex[1:], 16)
            except ValueError as exc:
                raise ValueError(f"Row {row_idx}, column {col_idx} has invalid color value: {value}") from exc

            symbol = symbol_by_hex.get(color_hex)
            if symbol is None:
                symbol = f"C{len(symbol_by_hex) + 1}"
                symbol_by_hex[color_hex] = symbol
                legend.append({
                    "symbol": symbol,
                    "color_hex": color_hex,
                    "confidence": 1.0,
                    "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
                })

            cells.append({
                "row": row_idx,
                "col": col_idx,
                "symbol": symbol,
                "color_hex": color_hex,
                "empty": False,
            })

    return {
        "rows": len(rows),
        "cols": cols,
        "cells": cells,
        "legend": legend,
        "artifacts": {"source": "csv_import"},
        "image": {"source_name": source_name or "pattern.csv"},
    }


def _make_background_mask(img: np.ndarray) -> np.ndarray:
    """Return a boolean mask (same H×W as img) that is True for background pixels.

    Operates in grayscale so that anti-aliased border pixels (which are near-white
    regardless of their color tint) are captured by a single-channel tolerance,
    rather than failing a per-channel BGR comparison.
    FLOODFILL_FIXED_RANGE compares each candidate pixel against the seed value
    (the white corner), not its neighbor, preventing the fill from walking through
    gradients into the subject interior.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_3ch = cv2.merge([gray, gray, gray])

    flood = gray_3ch.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    marker = (1, 254, 1)
    # diff=50 on grayscale: floods gray >= 205 (covers white + anti-aliased grey zone)
    diff = (50, 50, 50)
    flags = 4 | cv2.FLOODFILL_FIXED_RANGE
    seeds = [
        (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),   # corners
        (w // 2, 0), (w // 2, h - 1),                       # top / bottom midpoints
        (0, h // 2), (w - 1, h // 2),                       # left / right midpoints
    ]
    for seed in seeds:
        cv2.floodFill(flood, ff_mask, seed, marker, loDiff=diff, upDiff=diff, flags=flags)
    return np.all(flood == marker, axis=2)   # (h, w) bool


def _convert_image_to_grid(img_path: str, grid_size: str, quality: int) -> dict:
    """Sharp photo-to-bead conversion with pixel-accurate outline removal.

    Pipeline:
      0. Build hi-res background mask via flood-fill on the ORIGINAL image.
      1. Saturation boost (+40 %) — vivid bead colours.
      2. CLAHE in LAB (clipLimit=3) — local contrast preserved through downscale.
      3. Pre-downscale unsharp mask — edges stay crisp through pixelation.
      4. INTER_AREA downscale — clean box-average, no ringing or blur.
      5. Bilateral filter on small grid — edge-preserving within-region smoothing.
      6. Post-downscale unsharp mask — pops each bead cell's boundary.
      7. k-means++ — solid-block colours, no dithering.
      8. Mark cells empty when >50 % of their hi-res source pixels were background.
    """
    w_str, h_str = grid_size.lower().split("x")
    max_cols, max_rows = int(w_str), int(h_str)

    img = cv2.imread(img_path)
    if img is None:
        raise ValueError(f"Cannot read image: {img_path}")

    img_h, img_w = img.shape[:2]

    # Preserve aspect ratio within the selected bounding box
    if img_w * max_rows >= img_h * max_cols:
        cols = max_cols
        rows = max(1, round(max_cols * img_h / img_w))
    else:
        rows = max_rows
        cols = max(1, round(max_rows * img_w / img_h))

    # 0. Hi-res background mask on the ORIGINAL image (before any colour changes)
    bg_pixel_mask = _make_background_mask(img)   # True = background pixel
    cell_w_orig = img_w / cols
    cell_h_orig = img_h / rows

    # 1. Saturation boost in HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.4, 0, 255)
    img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # 2. CLAHE for local contrast in LAB space
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l_ch = clahe.apply(l_ch)
    img = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)

    # 3. Pre-downscale unsharp mask — edges survive pixelation
    blur_pre = cv2.GaussianBlur(img, (0, 0), 1.5)
    img = cv2.addWeighted(img, 2.0, blur_pre, -1.0, 0)

    # 4. INTER_AREA downscale (box-average, alias-free)
    small = cv2.resize(img, (cols, rows), interpolation=cv2.INTER_AREA)

    # 5. Bilateral filter — edge-preserving within-region smoothing
    small = cv2.bilateralFilter(small, d=3, sigmaColor=50, sigmaSpace=3)

    # 6. Post-downscale unsharp mask — pop bead-level edges
    blur_post = cv2.GaussianBlur(small, (3, 3), 0)
    small = cv2.addWeighted(small, 1.5, blur_post, -0.5, 0)

    # 7. k-means++ colour quantisation — solid blocks, no dithering
    pixels = small.reshape(-1, 3).astype(np.float32)
    num_colors = max(4, min(12, round(4 + (quality - 50) / 50 * 8)))
    k = min(num_colors, len(np.unique(pixels.astype(np.int32), axis=0)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
    centers_int = centers.astype(int)
    labels_flat = labels.flatten()
    label_grid = labels_flat.reshape(rows, cols)

    symbols = [chr(65 + i) if i < 26 else f"C{i - 25:02d}" for i in range(k)]

    def _hex(c: np.ndarray) -> str:
        return "#{:02X}{:02X}{:02X}".format(int(c[2]), int(c[1]), int(c[0]))

    legend = [
        {"symbol": symbols[i], "color_hex": _hex(centers_int[i]),
         "confidence": 1.0, "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0}}
        for i in range(k)
    ]

    # 8. Build cells — empty when majority of hi-res source pixels were background
    cells = []
    for ry in range(rows):
        for cx in range(cols):
            idx = int(label_grid[ry, cx])
            ctr = centers_int[idx]

            # Background coverage in the original full-resolution image
            x1 = int(cx * cell_w_orig)
            y1 = int(ry * cell_h_orig)
            x2 = max(int((cx + 1) * cell_w_orig), x1 + 1)
            y2 = max(int((ry + 1) * cell_h_orig), y1 + 1)
            patch_bg = bg_pixel_mask[y1:y2, x1:x2]
            flood_bg_ratio = float(patch_bg.mean())

            # Also check if the k-means cluster color is near-white/desaturated.
            # INTER_AREA mixes background + outline pixels in border cells, producing
            # a washed-out color. Those cells should be treated as empty even when
            # the flood-fill background ratio is only moderate (~0.2-0.5).
            ctr_hsv = cv2.cvtColor(
                np.array([[ctr]], dtype=np.uint8), cv2.COLOR_BGR2HSV
            )[0, 0]
            cluster_near_white = int(ctr_hsv[1]) < 30 and int(ctr_hsv[2]) > 210

            # Empty when: clearly background (>50 %), or border cell with washed-out color.
            # The flood_bg_ratio > 0.2 guard keeps interior near-white cells (reflections,
            # white clothing) from being removed when they are surrounded by character pixels.
            is_empty = bool(
                flood_bg_ratio > 0.5
                or (flood_bg_ratio > 0.2 and cluster_near_white)
            )

            cells.append({
                "row": ry + 1, "col": cx + 1,
                "symbol": "" if is_empty else symbols[idx],
                "color_hex": "#FFFFFF" if is_empty else _hex(ctr),
                "cluster_id": -1 if is_empty else idx,
                "empty": is_empty,
                "confidence": 1.0, "needs_review": False,
            })

    return {
        "rows": rows, "cols": cols, "cells": cells, "legend": legend,
        "artifacts": {}, "image": {"source_name": os.path.basename(img_path)},
    }


def _build_pattern_data(result: dict) -> tuple:
    cells = result.get("cells", [])
    legend = result.get("legend", [])
    rows = result.get("rows", 0)
    cols = result.get("cols", 0)

    grid_data = [[""] * cols for _ in range(rows)]
    for cell in cells:
        r, c = cell["row"] - 1, cell["col"] - 1
        if 0 <= r < rows and 0 <= c < cols and not cell.get("empty", False):
            grid_data[r][c] = cell["symbol"]

    palette = [
        {"id": e["symbol"], "name": e.get("name") or e["symbol"], "hex": e["color_hex"]}
        for e in legend
    ]
    preview_color = palette[0]["hex"] if palette else "#CC2936"
    return grid_data, palette, rows, cols, preview_color


@router.post("/upload")
async def upload_and_process(
    file: UploadFile = File(...),
    palette_name: str = Form("MARD"),
    quality: int = Form(85),
    is_grid_image: str = Form("false"),
    current_user: models.User = Depends(get_admin_user),
):
    use_ocr = is_grid_image.lower() in ("true", "1", "yes")
    selected_palette = _validate_palette_name(palette_name)
    is_csv = _is_csv_upload(file)
    if not is_csv and (not file.content_type or not file.content_type.startswith("image/")):
        raise HTTPException(status_code=400, detail="File must be an image (JPEG, PNG, WEBP) or CSV bead pattern")

    contents = await file.read()
    if is_csv:
        try:
            result = _csv_to_processing_result(contents, file.filename or "pattern.csv")
            return apply_color_system_to_result(result, selected_palette)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"CSV import failed: {exc}") from exc

    suffix = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"

    with tempfile.TemporaryDirectory() as workdir:
        img_path = os.path.join(workdir, f"source{suffix}")
        with open(img_path, "wb") as f:
            f.write(contents)

        try:
            if use_ocr:
                from grid_recovery import generate_web_result  # noqa: PLC0415
                result = generate_web_result(img_path, workdir)
                return apply_color_system_to_result(result, selected_palette)
            else:
                variants: dict = {}
                errors: list[str] = []
                for size in _PHOTO_SIZES:
                    try:
                        result = _convert_image_to_grid(img_path, size, quality)
                        variants[size] = apply_color_system_to_result(result, selected_palette)
                    except Exception as exc:
                        errors.append(f"{size}: {exc}")
                if not variants:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Processing failed for all sizes: {'; '.join(errors)}",
                    )
                return {"variants": variants}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Processing failed: {exc}") from exc


@router.post("/enhance-preview")
async def enhance_preview(
    file: UploadFile = File(...),
    grid_size: str = Form(...),
    palette_name: str = Form("MARD"),
    quality: int = Form(85),
    current_grid_json: Optional[str] = Form(None),
    current_user: models.User = Depends(get_admin_user),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (JPEG, PNG, WEBP)")
    if grid_size not in _PHOTO_SIZES:
        raise HTTPException(status_code=400, detail=f"grid_size must be one of {', '.join(_PHOTO_SIZES)}")
    selected_palette = _validate_palette_name(palette_name)

    contents = await file.read()
    suffix = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"

    with tempfile.TemporaryDirectory() as workdir:
        img_path = os.path.join(workdir, f"source{suffix}")
        with open(img_path, "wb") as f:
            f.write(contents)

        try:
            enhanced_path, ai_enhancement = enhance_image_for_beads(img_path, workdir)
            if not ai_enhancement.get("used") and _is_ai_image_edit_rejected(ai_enhancement):
                raise HTTPException(
                    status_code=422,
                    detail={"ai_enhancement": ai_enhancement},
                )
            grid_source_path = enhanced_path if ai_enhancement.get("used") else img_path
            if ai_enhancement.get("used"):
                try:
                    result = _convert_image_to_grid(enhanced_path, grid_size, quality)
                    result["ai_enhancement"] = ai_enhancement
                    result["ai_grid"] = {
                        "attempted": False,
                        "used": False,
                        "provider": "openai",
                        "reason": "deterministic_converter_used",
                    }
                    return apply_color_system_to_result(result, selected_palette)
                except Exception as conversion_exc:
                    ai_enhancement["deterministic_conversion_error"] = str(conversion_exc)

            grid_kwargs = {
                "grid_size": grid_size,
                "quality": quality,
                "ai_metadata": ai_enhancement,
            }
            if isinstance(current_grid_json, str) and current_grid_json.strip():
                grid_kwargs["current_grid_json"] = current_grid_json
            if ai_enhancement.get("used") and os.path.abspath(grid_source_path) != os.path.abspath(img_path):
                grid_kwargs["original_image_path"] = img_path
            ai_grid_result, ai_grid = generate_openai_bead_grid(
                grid_source_path,
                **grid_kwargs,
            )
            if ai_grid_result:
                return apply_color_system_to_result(ai_grid_result, selected_palette)
            if not ai_enhancement.get("used"):
                raise HTTPException(
                    status_code=422,
                    detail={"ai_enhancement": ai_enhancement, "ai_grid": ai_grid},
                )
            raise HTTPException(
                status_code=422,
                detail={"ai_enhancement": ai_enhancement, "ai_grid": ai_grid},
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"AI preview enhancement failed: {exc}") from exc


@router.post("/publish")
def publish_pattern(
    body: schemas.PublishRequest,
    current_user: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    grid_data, palette, rows, cols, preview_color = _build_pattern_data(body.processing_result)

    pattern = models.Pattern(
        title=body.title,
        tags=json.dumps(body.tags),
        size=body.size,
        grid_w=cols,
        grid_h=rows,
        faves_count=0,
        preview_color=preview_color,
        palette=json.dumps(palette),
        grid_data=json.dumps(grid_data),
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return {"id": pattern.id, "title": pattern.title, "grid_w": pattern.grid_w, "grid_h": pattern.grid_h}


@router.get("/stats")
def get_stats(
    current_user: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "total_patterns": db.query(models.Pattern).count(),
        "total_favorites": db.query(models.Favorite).count(),
    }
