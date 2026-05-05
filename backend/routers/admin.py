import csv
import io
import json
import os
import re
import tempfile
from typing import Optional

import cv2
import numpy as np
import pytesseract
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

import models
import schemas
from ai_enhancement import enhance_image_for_beads
from auth import get_admin_user
from color_systems import COLOR_SYSTEMS, _load_mapping, apply_color_system_to_result
from database import get_db
from openai_grid import generate_openai_bead_grid

router = APIRouter()

_PHOTO_SIZES = ["52x52", "78x78", "104x104"]
_CSV_CONTENT_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"}
_READY_GRID_IMPORT_MODE = "ready_grid_codes"
_READY_GRID_OCR_CONFIG = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_CODE_TOKEN_RE = re.compile(r"[A-Z]+[0-9]+")


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


def _normalize_ready_grid_code(value: object) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    if not compact or compact.isdigit():
        return ""
    known_codes = _known_mard_codes()
    candidates: list[str] = []

    for match in _CODE_TOKEN_RE.finditer(compact):
        candidates.append(match.group(0))

    if compact[0].isalpha() and len(compact) >= 2:
        digit_map = str.maketrans({
            "O": "0",
            "D": "0",
            "Q": "0",
            "I": "1",
            "L": "1",
            "T": "1",
            "Z": "2",
            "S": "5",
            "B": "8",
        })
        corrected_tail = compact[1:].translate(digit_map)
        corrected_digits = re.sub(r"[^0-9]", "", corrected_tail)
        for length in range(1, min(3, len(corrected_digits)) + 1):
            candidates.append(f"{compact[0]}{corrected_digits[:length]}")

    for candidate in candidates:
        if candidate in known_codes:
            return candidate
    return ""


def _looks_like_numbered_header_row(row: list[str]) -> bool:
    non_empty = [str(value or "").strip() for value in row if str(value or "").strip()]
    if not non_empty:
        return False
    numeric_count = sum(1 for value in non_empty if value.isdigit())
    code_count = sum(1 for value in non_empty if _CODE_TOKEN_RE.search(value))
    return numeric_count >= 2 and code_count == 0 and numeric_count / len(non_empty) >= 0.55


def _looks_like_numbered_header_column(rows: list[list[str]], index: int) -> bool:
    values = []
    for row in rows:
        if index >= len(row):
            continue
        value = str(row[index] or "").strip()
        if value:
            values.append(value)
    if not values:
        return False
    numeric_count = sum(1 for value in values if value.isdigit())
    code_count = sum(1 for value in values if _CODE_TOKEN_RE.search(value))
    return numeric_count >= 2 and code_count == 0 and numeric_count / len(values) >= 0.55


def _is_blue_header_hex(hex_value: str) -> bool:
    r, g, b = _hex_to_rgb_tuple(hex_value)
    return min(r, g, b) >= 220 and b - r >= 14 and b - g >= 5


def _looks_like_blue_header_row(colors: Optional[list[list[str]]], index: int) -> bool:
    if not colors or index >= len(colors):
        return False
    row = colors[index]
    if not row:
        return False
    blue_count = sum(1 for color in row if _is_blue_header_hex(_normalize_hex(color)))
    return blue_count >= 2 and blue_count / len(row) >= 0.6


def _looks_like_blue_header_column(colors: Optional[list[list[str]]], index: int) -> bool:
    if not colors:
        return False
    values = [row[index] for row in colors if index < len(row)]
    if not values:
        return False
    blue_count = sum(1 for color in values if _is_blue_header_hex(_normalize_hex(color)))
    return blue_count >= 2 and blue_count / len(values) >= 0.6


def _max_numeric_value(values: list[str]) -> Optional[int]:
    numbers = [int(value) for value in values if str(value or "").strip().isdigit()]
    return max(numbers) if numbers else None


def _target_body_dimensions(rows: list[list[str]]) -> tuple[Optional[int], Optional[int]]:
    if not rows:
        return None, None
    top_cols = _max_numeric_value(rows[0])
    bottom_cols = _max_numeric_value(rows[-1])
    body_rows = [row for row in rows if row and not _looks_like_numbered_header_row(row)]
    left_rows = _max_numeric_value([row[0] for row in body_rows])
    right_rows = _max_numeric_value([row[-1] for row in body_rows])
    return max([value for value in (left_rows, right_rows) if value is not None], default=None), max(
        [value for value in (top_cols, bottom_cols) if value is not None],
        default=None,
    )


def _trim_numbered_header_grid_and_colors(
    raw_grid: list[list[str]],
    color_grid: Optional[list[list[str]]] = None,
) -> tuple[list[list[str]], Optional[list[list[str]]]]:
    rows = [[str(cell or "").strip() for cell in row] for row in raw_grid if row]
    if not rows:
        return [], [] if color_grid is not None else None

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    target_rows, target_cols = _target_body_dimensions(rows)
    colors = None
    if color_grid is not None:
        colors = []
        for idx in range(len(rows)):
            color_row = color_grid[idx] if idx < len(color_grid) else []
            colors.append([_normalize_hex(cell) for cell in color_row] + ["#FFFFFF"] * (width - len(color_row)))

    while rows and (_looks_like_numbered_header_row(rows[0]) or _looks_like_blue_header_row(colors, 0)):
        rows = rows[1:]
        if colors is not None:
            colors = colors[1:]
    while rows and (_looks_like_numbered_header_row(rows[-1]) or _looks_like_blue_header_row(colors, len(rows) - 1)):
        rows = rows[:-1]
        if colors is not None:
            colors = colors[:-1]
    if not rows:
        return [], [] if color_grid is not None else None

    while rows and (_looks_like_numbered_header_column(rows, 0) or _looks_like_blue_header_column(colors, 0)):
        rows = [row[1:] for row in rows]
        if colors is not None:
            colors = [row[1:] for row in colors]
    while rows and rows[0] and (
        _looks_like_numbered_header_column(rows, len(rows[0]) - 1)
        or _looks_like_blue_header_column(colors, len(rows[0]) - 1)
    ):
        rows = [row[:-1] for row in rows]
        if colors is not None:
            colors = [row[:-1] for row in colors]

    if rows and target_rows and len(rows) < target_rows:
        row_width = len(rows[0])
        missing_rows = target_rows - len(rows)
        rows.extend([[""] * row_width for _ in range(missing_rows)])
        if colors is not None:
            colors.extend([["#FFFFFF"] * row_width for _ in range(missing_rows)])

    return [[_normalize_ready_grid_code(cell) for cell in row] for row in rows], colors


def _trim_numbered_header_grid(raw_grid: list[list[str]]) -> list[list[str]]:
    rows, _ = _trim_numbered_header_grid_and_colors(raw_grid)
    return rows


def _normalize_hex(hex_value: object, fallback: str = "#FFFFFF") -> str:
    raw = str(hex_value or "").strip().upper()
    if raw and not raw.startswith("#"):
        raw = f"#{raw}"
    if len(raw) == 7:
        try:
            int(raw[1:], 16)
            return raw
        except ValueError:
            pass
    return fallback


def _known_mard_codes() -> set[str]:
    return {str(codes.get("MARD") or "").upper() for codes in _load_mapping().values() if codes.get("MARD")}


def _mard_hex_for_code(code: str, fallback: str) -> str:
    normalized = str(code or "").strip().upper()
    for hex_value, codes in _load_mapping().items():
        if str(codes.get("MARD") or "").upper() == normalized:
            return _normalize_hex(hex_value, fallback)
    return _normalize_hex(fallback)


def _hex_to_rgb_tuple(hex_value: str) -> tuple[int, int, int]:
    normalized = _normalize_hex(hex_value)
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def _color_distance_sq(a: str, b: str) -> int:
    ar, ag, ab = _hex_to_rgb_tuple(a)
    br, bg, bb = _hex_to_rgb_tuple(b)
    return (ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2


def _is_empty_ready_grid_color(hex_value: str) -> bool:
    r, g, b = _hex_to_rgb_tuple(hex_value)
    return min(r, g, b) >= 248 and max(r, g, b) - min(r, g, b) <= 8


def _assign_ready_grid_codes_from_legend_colors(
    code_grid: list[list[str]],
    color_grid: list[list[str]],
    legend_entries: list[dict],
) -> list[list[str]]:
    if not legend_entries:
        return [[_normalize_ready_grid_code(cell) for cell in row] for row in code_grid]

    legend_colors = [
        (_normalize_ready_grid_code(entry.get("symbol")), _normalize_hex(entry.get("color_hex")))
        for entry in legend_entries
    ]
    legend_colors = [(symbol, color_hex) for symbol, color_hex in legend_colors if symbol]
    legend_by_symbol = {symbol: color_hex for symbol, color_hex in legend_colors}
    if not legend_colors:
        return [[_normalize_ready_grid_code(cell) for cell in row] for row in code_grid]

    assigned: list[list[str]] = []
    for row_idx, row in enumerate(code_grid):
        assigned_row: list[str] = []
        for col_idx, raw_symbol in enumerate(row):
            sampled_hex = "#FFFFFF"
            if row_idx < len(color_grid) and col_idx < len(color_grid[row_idx]):
                sampled_hex = _normalize_hex(color_grid[row_idx][col_idx])

            raw_symbol = _normalize_ready_grid_code(raw_symbol)
            if raw_symbol in legend_by_symbol and _color_distance_sq(sampled_hex, legend_by_symbol[raw_symbol]) <= 2200:
                assigned_row.append(raw_symbol)
                continue

            if not _is_empty_ready_grid_color(sampled_hex):
                nearest_symbol = ""
                nearest_distance = float("inf")
                for candidate_symbol, candidate_hex in legend_colors:
                    distance = _color_distance_sq(sampled_hex, candidate_hex)
                    if distance < nearest_distance:
                        nearest_symbol = candidate_symbol
                        nearest_distance = distance
                if nearest_symbol and nearest_distance <= 1200:
                    assigned_row.append(nearest_symbol)
                    continue

            assigned_row.append(raw_symbol)
        assigned.append(assigned_row)
    return assigned


def _recover_ready_grid_symbols(
    code_grid: list[list[str]],
    color_grid: Optional[list[list[str]]],
    legend_entries: Optional[list[dict]] = None,
) -> list[list[str]]:
    if color_grid and legend_entries:
        code_grid = _assign_ready_grid_codes_from_legend_colors(code_grid, color_grid, legend_entries)

    normalized = [[_normalize_ready_grid_code(cell) for cell in row] for row in code_grid]
    if not color_grid:
        return normalized

    for row_idx, row in enumerate(normalized):
        for col_idx, symbol in enumerate(row):
            if not symbol or row_idx >= len(color_grid) or col_idx >= len(color_grid[row_idx]):
                continue
            sampled_hex = _normalize_hex(color_grid[row_idx][col_idx])
            expected_hex = _mard_hex_for_code(symbol, sampled_hex)
            if _color_distance_sq(sampled_hex, expected_hex) > 5200:
                normalized[row_idx][col_idx] = ""

    symbol_colors: dict[str, list[str]] = {}
    for row_idx, row in enumerate(normalized):
        for col_idx, symbol in enumerate(row):
            if not symbol or row_idx >= len(color_grid) or col_idx >= len(color_grid[row_idx]):
                continue
            symbol_colors.setdefault(symbol, []).append(_normalize_hex(color_grid[row_idx][col_idx]))

    reference_colors = {
        symbol: max(set(colors), key=colors.count)
        for symbol, colors in symbol_colors.items()
        if colors
    }
    recovered: list[list[str]] = []
    for row_idx, row in enumerate(normalized):
        recovered_row: list[str] = []
        for col_idx, symbol in enumerate(row):
            if symbol:
                recovered_row.append(symbol)
                continue

            sampled_hex = "#FFFFFF"
            if row_idx < len(color_grid) and col_idx < len(color_grid[row_idx]):
                sampled_hex = _normalize_hex(color_grid[row_idx][col_idx])
            if _is_empty_ready_grid_color(sampled_hex):
                recovered_row.append("")
                continue

            nearest_symbol = ""
            nearest_distance = float("inf")
            for candidate_symbol, candidate_hex in reference_colors.items():
                distance = _color_distance_sq(sampled_hex, candidate_hex)
                if distance < nearest_distance:
                    nearest_symbol = candidate_symbol
                    nearest_distance = distance
            if nearest_symbol and nearest_distance <= 1800:
                recovered_row.append(nearest_symbol)
                continue

            recovered_row.append("")
        recovered.append(recovered_row)
    return recovered


def _code_grid_to_processing_result(
    code_grid: list[list[str]],
    color_grid: Optional[list[list[str]]] = None,
    *,
    source_name: str,
    legend_entries: Optional[list[dict]] = None,
) -> dict:
    if not code_grid:
        raise ValueError("No bead codes found in the grid image")

    code_grid = _recover_ready_grid_symbols(code_grid, color_grid, legend_entries)
    cols = max(len(row) for row in code_grid)
    rows = len(code_grid)
    cells = []
    legend = []
    seen_symbols: set[str] = set()

    for row_idx, row in enumerate(code_grid, start=1):
        for col_idx in range(1, cols + 1):
            symbol = _normalize_ready_grid_code(row[col_idx - 1] if col_idx - 1 < len(row) else "")
            sampled_hex = "#FFFFFF"
            if color_grid and row_idx - 1 < len(color_grid) and col_idx - 1 < len(color_grid[row_idx - 1]):
                sampled_hex = _normalize_hex(color_grid[row_idx - 1][col_idx - 1])

            if not symbol:
                cells.append({
                    "row": row_idx,
                    "col": col_idx,
                    "symbol": "",
                    "color_hex": "#FFFFFF",
                    "empty": True,
                    "confidence": 1.0,
                    "needs_review": False,
                })
                continue

            color_hex = _mard_hex_for_code(symbol, sampled_hex)
            if symbol not in seen_symbols:
                legend.append({
                    "symbol": symbol,
                    "color_hex": color_hex,
                    "confidence": 1.0,
                    "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
                })
                seen_symbols.add(symbol)

            cells.append({
                "row": row_idx,
                "col": col_idx,
                "symbol": symbol,
                "color_hex": color_hex,
                "empty": False,
                "confidence": 1.0,
                "needs_review": False,
            })

    return {
        "rows": rows,
        "cols": cols,
        "cells": cells,
        "legend": legend,
        "artifacts": {"source": "ready_grid_image_import"},
        "image": {"source_name": source_name or "ready-grid.png"},
    }


def _line_centers_from_projection(projection: np.ndarray, min_strength: float) -> list[int]:
    if projection.size == 0:
        return []
    threshold = max(min_strength, float(projection.max()) * 0.25)
    indices = np.where(projection >= threshold)[0]
    if len(indices) == 0:
        return []

    centers: list[int] = []
    start = int(indices[0])
    previous = int(indices[0])
    for index in indices[1:]:
        index = int(index)
        if index - previous > 3:
            centers.append(int(round((start + previous) / 2)))
            start = index
        previous = index
    centers.append(int(round((start + previous) / 2)))
    return centers


def _trim_irregular_line_centers(centers: list[int]) -> list[int]:
    if len(centers) < 4:
        return centers
    diffs = np.diff(centers)
    regular_diffs = [int(d) for d in diffs if d > 12]
    if not regular_diffs:
        return centers
    period = float(np.median(regular_diffs))
    runs: list[list[int]] = []
    current = [centers[0]]
    for next_center, diff in zip(centers[1:], diffs):
        if period * 0.55 <= diff <= period * 1.45:
            current.append(next_center)
        else:
            if len(current) >= 4:
                runs.append(current)
            current = [next_center]
    if len(current) >= 4:
        runs.append(current)
    return max(runs, key=len) if runs else centers


def _detect_ready_grid_lines(image: np.ndarray) -> tuple[list[int], list[int]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        51,
        15,
    )
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, image.shape[1] // 70), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, image.shape[0] // 100)))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    x_lines = _line_centers_from_projection(v_lines.sum(axis=0) / 255.0, max(12, image.shape[0] * 0.15))
    y_lines = _line_centers_from_projection(h_lines.sum(axis=1) / 255.0, max(12, image.shape[1] * 0.15))
    x_lines = _trim_irregular_line_centers(x_lines)
    y_lines = _trim_irregular_line_centers(y_lines)
    if len(x_lines) < 3 or len(y_lines) < 3:
        raise ValueError("Unable to detect numbered grid lines")
    return x_lines, y_lines


def _cell_fill_hex(cell: np.ndarray) -> str:
    if cell.size == 0:
        return "#FFFFFF"
    h, w = cell.shape[:2]
    pad_y = max(1, int(h * 0.18))
    pad_x = max(1, int(w * 0.18))
    inner = cell[pad_y:max(pad_y + 1, h - pad_y), pad_x:max(pad_x + 1, w - pad_x)]
    if inner.size == 0:
        inner = cell
    rgb = cv2.cvtColor(inner, cv2.COLOR_BGR2RGB).reshape(-1, 3)
    median = np.median(rgb, axis=0).astype(int)
    return "#{:02X}{:02X}{:02X}".format(int(median[0]), int(median[1]), int(median[2]))


def _ocr_ready_grid_cell(cell: np.ndarray) -> str:
    if cell.size == 0:
        return ""
    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    text = pytesseract.image_to_string(gray, config=_READY_GRID_OCR_CONFIG)
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _extract_ready_grid_legend_entries(image: np.ndarray, grid_bottom: int) -> list[dict]:
    band = image[grid_bottom + 4:min(image.shape[0], grid_bottom + 700), :]
    if band.size == 0:
        return []
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    entries: list[dict] = []
    seen: set[str] = set()
    configs = [
        "--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789() ",
        "--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789() ",
    ]
    for scale in (2, 3):
        resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        for config in configs:
            text = pytesseract.image_to_string(resized, config=config)
            for match in _CODE_TOKEN_RE.finditer(str(text or "").upper()):
                symbol = _normalize_ready_grid_code(match.group(0))
                if not symbol or symbol in seen:
                    continue
                entries.append({
                    "symbol": symbol,
                    "color_hex": _mard_hex_for_code(symbol, "#FFFFFF"),
                    "confidence": 1.0,
                    "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
                })
                seen.add(symbol)
    return entries


def _extract_ready_grid_image_result(img_path: str) -> dict:
    image = cv2.imread(img_path)
    if image is None:
        raise ValueError(f"Cannot read image: {img_path}")

    x_lines, y_lines = _detect_ready_grid_lines(image)
    raw_codes: list[list[str]] = []
    raw_colors: list[list[str]] = []

    for y1, y2 in zip(y_lines, y_lines[1:]):
        code_row: list[str] = []
        color_row: list[str] = []
        for x1, x2 in zip(x_lines, x_lines[1:]):
            cell = image[y1 + 2:y2 - 2, x1 + 2:x2 - 2]
            code_row.append(_ocr_ready_grid_cell(cell))
            color_row.append(_cell_fill_hex(cell))
        raw_codes.append(code_row)
        raw_colors.append(color_row)

    trimmed_codes, color_rows = _trim_numbered_header_grid_and_colors(raw_codes, raw_colors)
    has_top_header = _looks_like_numbered_header_row(raw_codes[0]) or _looks_like_blue_header_row(raw_colors, 0)
    has_bottom_header = _looks_like_numbered_header_row(raw_codes[-1]) or _looks_like_blue_header_row(raw_colors, len(raw_colors) - 1)
    if has_top_header and has_bottom_header and len(trimmed_codes) < len(raw_codes) - 2:
        row_width = len(trimmed_codes[0]) if trimmed_codes else max(0, len(raw_codes[0]) - 2)
        missing_rows = len(raw_codes) - 2 - len(trimmed_codes)
        trimmed_codes.extend([[""] * row_width for _ in range(missing_rows)])
        if color_rows is not None:
            color_rows.extend([["#FFFFFF"] * row_width for _ in range(missing_rows)])

    has_left_header = _looks_like_numbered_header_column(raw_codes, 0) or _looks_like_blue_header_column(raw_colors, 0)
    has_right_header = _looks_like_numbered_header_column(raw_codes, len(raw_codes[0]) - 1) or _looks_like_blue_header_column(raw_colors, len(raw_codes[0]) - 1)
    expected_cols = len(raw_codes[0]) - 2 if has_left_header and has_right_header else None
    if expected_cols and trimmed_codes and len(trimmed_codes[0]) < expected_cols:
        missing_cols = expected_cols - len(trimmed_codes[0])
        trimmed_codes = [row + [""] * missing_cols for row in trimmed_codes]
        if color_rows is not None:
            color_rows = [row + ["#FFFFFF"] * missing_cols for row in color_rows]
    legend_entries = _extract_ready_grid_legend_entries(image, y_lines[-1])

    return _code_grid_to_processing_result(
        trimmed_codes,
        color_rows,
        source_name=os.path.basename(img_path),
        legend_entries=legend_entries,
    )


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
    import_mode: str = Form("auto"),
    current_user: models.User = Depends(get_admin_user),
):
    use_ocr = is_grid_image.lower() in ("true", "1", "yes")
    ready_grid_import = import_mode == _READY_GRID_IMPORT_MODE
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
            if ready_grid_import:
                result = _extract_ready_grid_image_result(img_path)
                result["palette_name"] = selected_palette
                return result
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
