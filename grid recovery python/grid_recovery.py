from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageDraw, ImageFont

from grid_web_export import build_web_export_payload


TOKEN_RE = re.compile(r"[A-Z0-9]{1,3}")
OCR_CONFIG = "--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
LEGEND_OCR_CONFIG = "--psm 6 -c tessedit_char_whitelist=0123456789"
FOOTER_LABEL_OCR_CONFIG = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NUMERIC_OCR_CONFIG = "--psm 6 -c tessedit_char_whitelist=0123456789"
FOOTER_SLOT_DIGIT_MAP = str.maketrans(
    {
        "O": "0",
        "D": "0",
        "Q": "9",
        "Y": "9",
        "Z": "2",
        "S": "5",
        "B": "8",
    }
)


@dataclass(frozen=True)
class GridLayout:
    left: int
    top: int
    width: int
    height: int
    cell_size: int
    rows: int
    cols: int
    x_lines: List[int]
    y_lines: List[int]


@dataclass(frozen=True)
class BorderLabelCounts:
    rows: int | None = None
    cols: int | None = None
    first_row_center_y: float | None = None
    last_row_center_y: float | None = None


@dataclass(frozen=True)
class LegendEntry:
    symbol: str
    color_bgr: tuple[int, int, int]
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass
class CellRecord:
    row: int
    col: int
    bbox: Tuple[int, int, int, int]
    color_bgr: Tuple[int, int, int]
    color_hex: str
    is_empty: bool
    raw_symbol: str
    raw_confidence: float
    symbol: str = ""
    confidence: float = 0.0
    cluster_id: int = -1
    needs_review: bool = False
    high_risk: bool = False


def build_legend_table(entries: list[LegendEntry]) -> dict[str, LegendEntry]:
    legend: dict[str, LegendEntry] = {}
    for entry in entries:
        existing = legend.get(entry.symbol)
        if existing is None or entry.confidence > existing.confidence:
            legend[entry.symbol] = entry
    return legend


def _derive_legend_entries_from_clusters(cells: list[CellRecord]) -> list[LegendEntry]:
    grouped: dict[int, list[CellRecord]] = defaultdict(list)
    for cell in cells:
        if cell.is_empty or cell.cluster_id < 0:
            continue
        grouped[cell.cluster_id].append(cell)

    entries: list[LegendEntry] = []
    for cluster_id in sorted(grouped):
        cluster_cells = grouped[cluster_id]
        samples = np.array([cell.color_bgr for cell in cluster_cells], dtype=np.float32)
        color_bgr = _median_color(samples)
        entries.append(
            LegendEntry(
                symbol=f"C{cluster_id:02d}",
                color_bgr=color_bgr,
                bbox=(0, 0, 0, 0),
                confidence=0.25,
            )
        )
    return entries


def _choose_legend_entries(
    extracted_entries: list[LegendEntry],
    cluster_entries: list[LegendEntry],
) -> list[LegendEntry]:
    if not extracted_entries:
        return cluster_entries
    if (
        cluster_entries
        and len(extracted_entries) < min(6, len(cluster_entries))
        and max(entry.confidence for entry in extracted_entries) <= 0.25
    ):
        return cluster_entries
    return extracted_entries


def _group_indices(indices: np.ndarray) -> List[int]:
    if len(indices) == 0:
        return []
    groups: List[int] = []
    start = int(indices[0])
    prev = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value == prev + 1:
            prev = value
            continue
        groups.append((start + prev) // 2)
        start = value
        prev = value
    groups.append((start + prev) // 2)
    return groups


def _estimate_period(projection: np.ndarray) -> int:
    strong = np.where(projection > projection.max() * 0.45)[0]
    centers = _group_indices(strong)
    diffs = np.diff(centers)
    diffs = diffs[(diffs >= 8) & (diffs <= 30)]
    if len(diffs) == 0:
        raise ValueError("Unable to estimate grid period")
    return int(np.median(diffs))


def _refine_lines(projection: np.ndarray, cell_size: int) -> List[int]:
    strong = np.where(projection > projection.max() * 0.45)[0]
    centers = _group_indices(strong)
    if not centers:
        raise ValueError("Unable to detect grid lines")

    start = centers[0]
    refined = []
    guess = start
    while guess < len(projection) - 2:
        lo = max(0, int(round(guess - cell_size * 0.35)))
        hi = min(len(projection), int(round(guess + cell_size * 0.35)) + 1)
        if hi <= lo:
            break
        local = projection[lo:hi]
        peak = lo + int(np.argmax(local))
        refined.append(peak)
        guess = peak + cell_size

    deduped: List[int] = []
    for value in refined:
        if not deduped or value - deduped[-1] >= cell_size * 0.6:
            deduped.append(value)
    return deduped


def _trim_trailing_irregular_lines(lines: List[int], cell_size: int) -> List[int]:
    if len(lines) < 4:
        return lines

    diffs = np.diff(lines)
    lower = cell_size * 0.8
    upper = cell_size * 1.25
    start_scan = max(0, len(diffs) // 2)
    invalid_run = 0

    for idx, diff in enumerate(diffs):
        if idx < start_scan:
            continue
        if lower <= diff <= upper:
            invalid_run = 0
            continue
        invalid_run += 1
        if invalid_run >= 3:
            cutoff = idx - invalid_run + 2
            return lines[:cutoff]

    if not (lower <= diffs[-1] <= upper):
        return lines[:-1]
    return lines


def _ocr_numeric_tokens(patch: np.ndarray, *, scale: int = 6) -> list[tuple[int, float, float, float, float, float]]:
    if patch.size == 0:
        return []

    enlarged = cv2.resize(patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    data = pytesseract.image_to_data(
        threshold,
        config=NUMERIC_OCR_CONFIG,
        output_type=pytesseract.Output.DICT,
    )

    tokens: list[tuple[int, float, float, float, float, float]] = []
    for text, confidence, left, top, width, height in zip(
        data["text"],
        data["conf"],
        data["left"],
        data["top"],
        data["width"],
        data["height"],
    ):
        raw = text.strip()
        if re.fullmatch(r"\d{1,3}", raw) is None:
            continue
        try:
            score = float(confidence)
        except ValueError:
            score = -1.0
        tokens.append(
            (
                int(raw),
                score,
                left / scale,
                top / scale,
                width / scale,
                height / scale,
            )
        )
    return tokens


def _detect_border_label_counts(image: np.ndarray, layout: GridLayout) -> BorderLabelCounts:
    side_width = max(32, int(round(layout.cell_size * 2.0)))
    y1 = max(0, layout.top + layout.y_lines[0] - layout.cell_size * 2)
    y2 = min(image.shape[0], layout.top + layout.y_lines[-1] + layout.cell_size * 2)
    if y2 <= y1:
        return BorderLabelCounts()

    left_tokens = _ocr_numeric_tokens(image[y1:y2, :side_width])
    right_x1 = max(0, image.shape[1] - side_width)
    right_tokens = _ocr_numeric_tokens(image[y1:y2, right_x1:])

    row_candidates: list[int] = []
    row_centers: dict[int, list[float]] = defaultdict(list)
    min_row = max(2, int(round(layout.rows * 0.5)))
    max_row = max(layout.rows + 2, min_row)

    for value, confidence, x, y, width, height in left_tokens:
        if confidence < 40 or x > side_width * 0.6:
            continue
        if 1 <= value <= max_row:
            row_centers[value].append(y1 + y + height / 2.0)
        if min_row <= value <= max_row:
            row_candidates.append(value)

    for value, confidence, x, y, width, height in right_tokens:
        if confidence < 40 or x < side_width * 0.4:
            continue
        if 1 <= value <= max_row:
            row_centers[value].append(y1 + y + height / 2.0)
        if min_row <= value <= max_row:
            row_candidates.append(value)

    col_candidates: list[int] = []
    min_col = max(2, layout.cols - 3)
    max_col = layout.cols + 3
    for value, confidence, x, _, _, _ in right_tokens:
        if confidence < 40 or x > side_width * 0.4:
            continue
        if min_col <= value <= max_col:
            col_candidates.append(value)

    rows = max(row_candidates) if row_candidates else None
    first_center = None
    last_center = None
    if rows is not None:
        if row_centers.get(1):
            first_center = float(np.median(row_centers[1]))
        if row_centers.get(rows):
            last_center = float(np.median(row_centers[rows]))

    return BorderLabelCounts(
        rows=rows,
        cols=max(col_candidates) if col_candidates else None,
        first_row_center_y=first_center,
        last_row_center_y=last_center,
    )


def _normalize_line_count(
    lines: list[int],
    *,
    target_cells: int,
    cell_size: int,
    leading_missing: bool = False,
    lower_bound: int = 0,
    upper_bound: int | None = None,
) -> list[int]:
    adjusted = list(lines)
    target_len = target_cells + 1
    if target_len < 2:
        return adjusted

    if leading_missing and adjusted:
        candidate = adjusted[0] - cell_size
        if candidate >= lower_bound and (not adjusted or adjusted[0] - candidate >= cell_size * 0.6):
            adjusted.insert(0, int(round(candidate)))

    while len(adjusted) < target_len and adjusted:
        prepend = adjusted[0] - cell_size
        append = adjusted[-1] + cell_size
        can_prepend = prepend >= lower_bound and adjusted[0] > cell_size * 1.2
        can_append = upper_bound is None or upper_bound - adjusted[-1] > cell_size * 1.2
        if can_prepend:
            adjusted.insert(0, int(round(prepend)))
        elif can_append:
            adjusted.append(int(round(append)))
        else:
            break

    if len(adjusted) > target_len:
        adjusted = adjusted[:target_len]
    return adjusted


def _apply_border_label_counts(layout: GridLayout, counts: BorderLabelCounts) -> GridLayout:
    target_cols = counts.cols or layout.cols
    target_rows = counts.rows or layout.rows

    first_y_abs = layout.top + layout.y_lines[0]
    leading_row_missing = (
        counts.first_row_center_y is not None
        and counts.first_row_center_y < first_y_abs
    )

    x_lines = _normalize_line_count(
        layout.x_lines,
        target_cells=target_cols,
        cell_size=layout.cell_size,
        lower_bound=0,
        upper_bound=layout.width,
    )
    y_lines = _normalize_line_count(
        layout.y_lines,
        target_cells=target_rows,
        cell_size=layout.cell_size,
        leading_missing=leading_row_missing,
        lower_bound=0,
        upper_bound=layout.height,
    )

    return GridLayout(
        left=layout.left,
        top=layout.top,
        width=layout.width,
        height=layout.height,
        cell_size=layout.cell_size,
        rows=max(0, len(y_lines) - 1),
        cols=max(0, len(x_lines) - 1),
        x_lines=x_lines,
        y_lines=y_lines,
    )


def _correct_layout_from_border_labels(image: np.ndarray, layout: GridLayout) -> GridLayout:
    counts = _detect_border_label_counts(image, layout)
    if counts.rows is None and counts.cols is None:
        return layout
    return _apply_border_label_counts(layout, counts)


def detect_grid_layout(image: np.ndarray) -> GridLayout:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        15,
        8,
    )
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    mask = cv2.bitwise_or(h_lines, v_lines)

    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        raise ValueError("Unable to locate grid region")

    left = int(xs.min())
    top = int(ys.min())
    right = int(xs.max())
    bottom = int(ys.max())
    crop = image[top : bottom + 1, left : right + 1]
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    crop_binary = cv2.adaptiveThreshold(
        crop_gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        15,
        8,
    )
    crop_h = cv2.morphologyEx(crop_binary, cv2.MORPH_OPEN, h_kernel)
    crop_v = cv2.morphologyEx(crop_binary, cv2.MORPH_OPEN, v_kernel)

    col_projection = crop_v.sum(axis=0) / 255.0
    row_projection = crop_h.sum(axis=1) / 255.0
    cell_size = int(round((_estimate_period(col_projection) + _estimate_period(row_projection)) / 2))
    x_lines = _refine_lines(col_projection, cell_size)
    y_lines = _refine_lines(row_projection, cell_size)
    x_lines = _trim_trailing_irregular_lines(x_lines, cell_size)
    y_lines = _trim_trailing_irregular_lines(y_lines, cell_size)

    cols = max(0, len(x_lines) - 1)
    rows = max(0, len(y_lines) - 1)
    layout = GridLayout(
        left=left,
        top=top,
        width=right - left + 1,
        height=bottom - top + 1,
        cell_size=cell_size,
        rows=rows,
        cols=cols,
        x_lines=x_lines,
        y_lines=y_lines,
    )
    return _correct_layout_from_border_labels(image, layout)


def detect_legend_band(image: np.ndarray, layout: GridLayout) -> np.ndarray:
    grid_bottom = layout.top + layout.y_lines[-1]
    start = max(0, grid_bottom - layout.cell_size * 5)
    end = min(image.shape[0], grid_bottom)
    return image[start:end]


def _legend_footer_band(image: np.ndarray, layout: GridLayout) -> tuple[int, np.ndarray]:
    start = min(image.shape[0], layout.top + layout.y_lines[-1])
    end = min(image.shape[0], start + layout.cell_size * 5)
    return start, image[start:end]


def _expanded_legend_footer_band(image: np.ndarray, layout: GridLayout) -> tuple[int, np.ndarray]:
    start = min(image.shape[0], layout.top + layout.y_lines[-1])
    end = min(image.shape[0], start + layout.cell_size * 13)
    return start, image[start:end]


def _median_color(pixels: np.ndarray) -> tuple[int, int, int]:
    median = np.median(pixels.reshape(-1, 3).astype(np.float32), axis=0)
    return tuple(int(round(channel)) for channel in median)


def _sample_footer_swatch_color(
    footer: np.ndarray,
    layout: GridLayout,
    x1: int,
    y1: int,
    x2: int,
) -> tuple[int, int, int]:
    swatch_x1 = max(0, x1 - layout.cell_size)
    swatch_x2 = min(footer.shape[1], x2 + layout.cell_size)
    swatch_y1 = max(0, y1 - layout.cell_size * 2)
    swatch_y2 = max(swatch_y1 + 1, y1 - max(1, layout.cell_size // 3))
    swatch_patch = footer[swatch_y1:swatch_y2, swatch_x1:swatch_x2]
    if swatch_patch.size == 0:
        return (0, 0, 0)

    hsv = cv2.cvtColor(swatch_patch, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] > 45) & (hsv[:, :, 2] > 80)
    pixels = swatch_patch[mask]
    if pixels.size == 0:
        fallback_y1 = max(0, y1 - layout.cell_size)
        fallback_y2 = max(fallback_y1 + 1, y1)
        fallback_patch = footer[fallback_y1:fallback_y2, x1:x2]
        if fallback_patch.size == 0:
            return (0, 0, 0)
        pixels = fallback_patch
    return _median_color(pixels)


def _ocr_footer_label(patch: np.ndarray) -> Tuple[str, float]:
    if patch.size == 0:
        return "", 0.0

    best_symbol = ""
    best_confidence = 0.0
    enlarged = cv2.resize(patch, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    variants = [
        cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        ),
    ]
    for candidate in variants:
        data = pytesseract.image_to_data(
            candidate,
            config=FOOTER_LABEL_OCR_CONFIG,
            output_type=pytesseract.Output.DICT,
        )
        for text, confidence in zip(data["text"], data["conf"]):
            token = TOKEN_RE.search(text.upper())
            if token is None:
                continue
            try:
                score = float(confidence)
            except ValueError:
                score = -1.0
            if score > best_confidence:
                best_symbol = token.group(0)
                best_confidence = score
    return best_symbol, max(0.0, best_confidence) / 100.0


def _normalize_footer_slot_token(token: str) -> str:
    token = re.sub(r"[^A-Z0-9]", "", token.upper())
    if not token:
        return ""
    if token[0].isalpha():
        suffix = token[1:].translate(FOOTER_SLOT_DIGIT_MAP)
        suffix = re.sub(r"[^0-9]", "", suffix)
        return token[0] + suffix
    return re.sub(r"[^0-9]", "", token.translate(FOOTER_SLOT_DIGIT_MAP))


def _detect_structured_footer_swatches(footer: np.ndarray, layout: GridLayout) -> list[tuple[int, int, int, int]]:
    if footer.size == 0:
        return []

    gray = cv2.cvtColor(footer, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(footer, cv2.COLOR_BGR2HSV)
    mask = (((gray < 245) | (hsv[:, :, 1] > 20))).astype(np.uint8) * 255

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes: list[tuple[int, int, int, int]] = []
    for idx in range(1, num_labels):
        x, y, w, h, area = stats[idx]
        if area < layout.cell_size * layout.cell_size * 6:
            continue
        if w < layout.cell_size * 2.4 or h < layout.cell_size * 2.4:
            continue
        if y < layout.cell_size * 2 or y > layout.cell_size * 5:
            continue
        boxes.append((x, y, x + w, y + h))

    boxes.sort(key=lambda box: box[0])
    return boxes


def _infer_footer_slot_centers(
    swatch_boxes: list[tuple[int, int, int, int]],
    layout: GridLayout,
) -> list[float]:
    if len(swatch_boxes) < 5:
        return []

    swatch_centers = [((x1 + x2) / 2.0) for x1, _, x2, _ in swatch_boxes]
    diffs = [right - left for left, right in zip(swatch_centers, swatch_centers[1:])]
    if not diffs:
        return []

    pitch = float(np.median(diffs))
    if pitch < layout.cell_size * 4:
        return []
    if any(abs(diff - pitch) > layout.cell_size * 1.2 for diff in diffs):
        return []

    slot_centers = list(swatch_centers)
    leading_center = swatch_centers[0] - pitch
    if leading_center > layout.cell_size * 3:
        slot_centers.insert(0, leading_center)
    return slot_centers


def _ocr_footer_slot_label(slot_patch: np.ndarray, layout: GridLayout) -> tuple[str, float]:
    if slot_patch.size == 0:
        return "", 0.0

    y_variants = [
        (int(round(layout.cell_size * 2.5)), int(round(layout.cell_size * 5.0))),
        (int(round(layout.cell_size * 2.75)), int(round(layout.cell_size * 5.0))),
    ]
    x_variants = [
        (int(round(layout.cell_size * 1.0)), int(round(layout.cell_size * 4.75))),
        (int(round(layout.cell_size * 0.5)), int(round(layout.cell_size * 5.0))),
    ]
    threshold_builders = (
        lambda gray: cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
        lambda gray: cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
    )

    exact_votes: dict[str, float] = defaultdict(float)
    letter_votes: dict[str, float] = defaultdict(float)
    digit_votes: dict[str, float] = defaultdict(float)

    for y1, y2 in y_variants:
        y1 = max(0, min(slot_patch.shape[0], y1))
        y2 = max(y1 + 1, min(slot_patch.shape[0], y2))
        for x1, x2 in x_variants:
            x1 = max(0, min(slot_patch.shape[1], x1))
            x2 = max(x1 + 1, min(slot_patch.shape[1], x2))
            crop = slot_patch[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            enlarged = cv2.resize(crop, None, fx=20, fy=20, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
            for threshold_builder in threshold_builders:
                thresholded = threshold_builder(gray)
                for psm in (7, 8, 13):
                    raw = pytesseract.image_to_string(
                        thresholded,
                        config=f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                    ).strip()
                    normalized = _normalize_footer_slot_token(raw)
                    if not normalized:
                        continue

                    base_score = 1.0 + (0.35 if psm in (8, 13) else 0.0)
                    full_match = re.fullmatch(r"[A-Z][0-9]{1,2}", normalized)
                    if full_match is not None:
                        exact_votes[normalized] += base_score + 2.0

                    if normalized[0].isalpha():
                        letter_votes[normalized[0]] += base_score
                        digits = normalized[1:]
                    else:
                        digits = normalized

                    if digits:
                        digit_votes[digits[:2]] += base_score
                        if len(digits) >= 2:
                            digit_votes[digits[-2:]] += base_score + 0.25
                        digit_votes[digits[:1]] += base_score * 0.7

    if exact_votes:
        symbol, score = max(exact_votes.items(), key=lambda item: (item[1], item[0]))
        return symbol, min(0.99, 0.5 + score / 12.0)

    if letter_votes and digit_votes:
        letter, letter_score = max(letter_votes.items(), key=lambda item: (item[1], item[0]))
        digits, digit_score = max(digit_votes.items(), key=lambda item: (item[1], item[0]))
        symbol = f"{letter}{digits}"
        return symbol, min(0.85, 0.35 + (letter_score + digit_score) / 16.0)

    return "", 0.0


def _extract_structured_footer_entries(image: np.ndarray, layout: GridLayout) -> list[LegendEntry]:
    footer_top, footer = _expanded_legend_footer_band(image, layout)
    swatch_boxes = _detect_structured_footer_swatches(footer, layout)
    slot_centers = _infer_footer_slot_centers(swatch_boxes, layout)
    if len(slot_centers) < 6:
        return []

    entries: list[LegendEntry] = []
    half_width = int(round(layout.cell_size * 2.75))
    slot_y1 = int(round(layout.cell_size * 1.75))
    slot_y2 = int(round(layout.cell_size * 6.75))

    for center in slot_centers:
        x1 = max(0, int(round(center - half_width)))
        x2 = min(footer.shape[1], int(round(center + half_width)))
        y1 = max(0, slot_y1)
        y2 = min(footer.shape[0], slot_y2)
        if x2 <= x1 or y2 <= y1:
            continue

        slot_patch = footer[y1:y2, x1:x2]
        symbol, confidence = _ocr_footer_slot_label(slot_patch, layout)
        if not symbol:
            continue

        matching_swatch = None
        for swatch_box in swatch_boxes:
            swatch_center = (swatch_box[0] + swatch_box[2]) / 2.0
            if abs(swatch_center - center) <= layout.cell_size * 1.75:
                matching_swatch = swatch_box
                break

        if matching_swatch is not None:
            sx1, sy1, sx2, sy2 = matching_swatch
            swatch_patch = footer[sy1:sy2, sx1:sx2]
            color_bgr = _median_color(swatch_patch)
            bbox = (sx1, footer_top + sy1, sx2, footer_top + sy2)
        else:
            background_patch = footer[
                int(round(layout.cell_size * 3.4)) : int(round(layout.cell_size * 6.2)),
                x1:x2,
            ]
            if background_patch.size == 0:
                color_bgr = (255, 255, 255)
            else:
                color_bgr = _median_color(background_patch)
            bbox = (x1, footer_top + y1, x2, footer_top + y2)

        entries.append(
            LegendEntry(
                symbol=symbol,
                color_bgr=color_bgr,
                bbox=bbox,
                confidence=confidence,
            )
        )

    if len(entries) >= 6:
        entries.sort(key=lambda entry: entry.bbox[0])
        return entries
    return []


def _ocr_legend_symbol(patch: np.ndarray) -> Tuple[str, float]:
    if patch.size == 0:
        return "", 0.0

    best_symbol = ""
    best_confidence = 0.0
    for top_fraction in (0.0, 0.15, 0.3):
        start = int(round(patch.shape[0] * top_fraction))
        subpatch = patch[start:]
        if subpatch.size == 0:
            continue
        enlarged = cv2.resize(subpatch, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        variants = [
            cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
        ]
        for candidate in variants:
            data = pytesseract.image_to_data(
                candidate,
                config=LEGEND_OCR_CONFIG,
                output_type=pytesseract.Output.DICT,
            )
            for text, confidence in zip(data["text"], data["conf"]):
                token = TOKEN_RE.search(text.upper())
                if token is None:
                    continue
                try:
                    score = float(confidence)
                except ValueError:
                    score = -1.0
                if score > best_confidence:
                    best_symbol = token.group(0)
                    best_confidence = score
    return best_symbol, max(0.0, best_confidence) / 100.0


def extract_legend_entries(image: np.ndarray, layout: GridLayout) -> List[LegendEntry]:
    structured_entries = _extract_structured_footer_entries(image, layout)
    if structured_entries:
        return structured_entries

    footer_top, footer = _legend_footer_band(image, layout)
    entries: List[LegendEntry] = []
    if footer.size != 0:
        hsv = cv2.cvtColor(footer, cv2.COLOR_BGR2HSV)
        swatch_mask = ((hsv[:, :, 1] > 35) & (hsv[:, :, 2] > 80)).astype(np.uint8) * 255
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(swatch_mask, 8)
        swatch_entries: List[LegendEntry] = []
        for idx in range(1, num_labels):
            x, y, w, h, area = stats[idx]
            if area < layout.cell_size * layout.cell_size * 2:
                continue
            if w < layout.cell_size * 2 or h < layout.cell_size:
                continue
            if y < footer.shape[0] * 0.4:
                continue

            label_patch = footer[
                max(0, y - layout.cell_size * 2) : max(0, y - 1),
                max(0, x - layout.cell_size // 2) : min(footer.shape[1], x + w + layout.cell_size // 2),
            ]
            symbol, confidence = _ocr_footer_label(label_patch)
            if not symbol or not any(char.isdigit() for char in symbol):
                symbol = f"S{len(swatch_entries) + 1}"
                confidence = max(confidence, 0.05)

            swatch_patch = footer[y : y + h, x : x + w]
            swatch_pixels = swatch_patch[swatch_mask[y : y + h, x : x + w] > 0]
            if swatch_pixels.size == 0:
                continue
            swatch_entries.append(
                LegendEntry(
                    symbol=symbol,
                    color_bgr=_median_color(swatch_pixels),
                    bbox=(x, footer_top + y, x + w, footer_top + y + h),
                    confidence=confidence,
                )
            )

        if len(swatch_entries) >= 5:
            swatch_entries.sort(key=lambda entry: entry.bbox[0])
            return swatch_entries

        scale = 12
        for text_top_fraction in (0.4, 0.45, 0.5, 0.55, 0.6):
            text_top = max(0, int(round(footer.shape[0] * text_top_fraction)))
            text_strip = footer[text_top:]
            if text_strip.size == 0:
                continue

            enlarged = cv2.resize(text_strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (3, 3), 0)
            threshold_variants = [
                cv2.adaptiveThreshold(
                    blur,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY_INV,
                    31,
                    11,
                ),
                cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
                cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            ]
            for threshold in threshold_variants:
                data = pytesseract.image_to_data(
                    threshold,
                    config=LEGEND_OCR_CONFIG,
                    output_type=pytesseract.Output.DICT,
                )
                for text, confidence, left, top, width, height in zip(
                    data["text"],
                    data["conf"],
                    data["left"],
                    data["top"],
                    data["width"],
                    data["height"],
                ):
                    token = TOKEN_RE.fullmatch(text.strip())
                    if token is None:
                        continue
                    try:
                        score = float(confidence)
                    except ValueError:
                        score = -1.0

                    x1 = int(round(left / scale))
                    y1 = int(round(text_top + top / scale))
                    x2 = int(round((left + width) / scale))
                    y2 = int(round(text_top + (top + height) / scale))
                    if x2 <= x1 or y2 <= y1:
                        continue
                    if y1 < int(round(footer.shape[0] * 0.35)):
                        continue

                    entries.append(
                        LegendEntry(
                            symbol=token.group(0),
                            color_bgr=_sample_footer_swatch_color(footer, layout, x1, y1, x2),
                            bbox=(x1, footer_top + y1, x2, footer_top + y2),
                            confidence=max(0.0, score) / 100.0,
                        )
                    )

    if entries:
        entries.sort(key=lambda entry: (entry.bbox[0], entry.bbox[1], -entry.confidence))
        return entries

    band_top = max(0, layout.top + layout.height - layout.cell_size * 5)
    band = image[band_top : min(image.shape[0], layout.top + layout.height)]
    if band.size == 0:
        return []

    legend_offset = band.shape[0] // 3
    legend_slice = band[legend_offset:]
    legend_top = band_top + legend_offset
    text_top = max(0, int(round(legend_slice.shape[0] * 0.6)))
    text_strip = legend_slice[text_top:]
    if text_strip.size == 0:
        return []

    scale = 10
    enlarged = cv2.resize(text_strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    threshold = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        11,
    )
    data = pytesseract.image_to_data(
        threshold,
        config=LEGEND_OCR_CONFIG,
        output_type=pytesseract.Output.DICT,
    )

    for text, confidence, left, top, width, height in zip(
        data["text"],
        data["conf"],
        data["left"],
        data["top"],
        data["width"],
        data["height"],
    ):
        token = TOKEN_RE.fullmatch(text.strip())
        if token is None:
            continue
        row_fraction = top / max(1, threshold.shape[0])
        if row_fraction < 0.35 or row_fraction > 0.65:
            continue
        try:
            score = float(confidence)
        except ValueError:
            score = -1.0

        x1 = int(round(left / scale))
        y1 = int(round(text_top + top / scale))
        x2 = int(round((left + width) / scale))
        y2 = int(round(text_top + (top + height) / scale))
        if x2 <= x1 or y2 <= y1:
            continue

        color_y1 = max(0, y1 - layout.cell_size)
        color_y2 = max(color_y1 + 1, y1)
        color_patch = legend_slice[color_y1:color_y2, x1:x2]
        if color_patch.size == 0:
            color_bgr = (0, 0, 0)
        else:
            color_bgr = _median_color(color_patch)

        entries.append(
            LegendEntry(
                symbol=token.group(0),
                color_bgr=color_bgr,
                bbox=(x1, legend_top + y1, x2, legend_top + y2),
                confidence=max(0.0, score) / 100.0,
            )
        )

    entries.sort(key=lambda entry: entry.bbox[0])
    return entries


def _dominant_color(patch: np.ndarray) -> Tuple[Tuple[int, int, int], bool]:
    inner = patch[1:-1, 1:-1] if min(patch.shape[:2]) > 2 else patch
    pixels = inner.reshape(-1, 3).astype(np.float32)
    median = np.median(pixels, axis=0)
    bgr = tuple(int(round(channel)) for channel in median)
    hsv = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
    is_empty = bool(hsv[1] < 28 and hsv[2] > 200)
    return bgr, is_empty


def _ocr_variants(patch: np.ndarray) -> Tuple[str, float]:
    variants = []
    base = cv2.resize(patch, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    thresholds = [
        cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        ),
    ]
    for candidate in thresholds:
        data = pytesseract.image_to_data(
            candidate,
            config=OCR_CONFIG,
            output_type=pytesseract.Output.DICT,
        )
        for text, confidence in zip(data["text"], data["conf"]):
            token = TOKEN_RE.search(text.upper())
            if token is None:
                continue
            try:
                value = float(confidence)
            except ValueError:
                value = -1.0
            variants.append((token.group(0), value))
    if not variants:
        return "", 0.0
    token, confidence = max(variants, key=lambda item: item[1])
    return token, max(0.0, confidence) / 100.0


def _extract_cells(image: np.ndarray, layout: GridLayout) -> List[CellRecord]:
    crop = image[layout.top : layout.top + layout.height, layout.left : layout.left + layout.width]
    cells: List[CellRecord] = []
    for row in range(layout.rows):
        for col in range(layout.cols):
            x1 = layout.x_lines[col]
            x2 = layout.x_lines[col + 1]
            y1 = layout.y_lines[row]
            y2 = layout.y_lines[row + 1]
            pad = 1 if min(x2 - x1, y2 - y1) > 4 else 0
            patch = crop[y1 + pad : y2 - pad, x1 + pad : x2 - pad]
            if patch.size == 0:
                continue
            color_bgr, is_empty = _dominant_color(patch)
            color_hex = "#{:02X}{:02X}{:02X}".format(color_bgr[2], color_bgr[1], color_bgr[0])
            cells.append(
                CellRecord(
                    row=row + 1,
                    col=col + 1,
                    bbox=(x1, y1, x2, y2),
                    color_bgr=color_bgr,
                    color_hex=color_hex,
                    is_empty=is_empty,
                    raw_symbol="",
                    raw_confidence=0.0,
                )
            )
    return cells


def _cluster_cells(cells: List[CellRecord], max_k: int = 14) -> None:
    colored = [cell for cell in cells if not cell.is_empty]
    if not colored:
        return
    samples = np.float32([cell.color_bgr for cell in colored])
    unique_count = len(np.unique(samples.astype(int), axis=0))
    k = max(2, min(max_k, unique_count))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 0.2)
    _, labels, centers = cv2.kmeans(samples, k, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    for cell, label in zip(colored, labels.flatten()):
        cell.cluster_id = int(label)
        center = centers[cell.cluster_id]
        cell.color_bgr = tuple(int(round(channel)) for channel in center)
        cell.color_hex = "#{:02X}{:02X}{:02X}".format(cell.color_bgr[2], cell.color_bgr[1], cell.color_bgr[0])


def _cell_patch(image: np.ndarray, layout: GridLayout, cell: CellRecord) -> np.ndarray:
    crop = image[layout.top : layout.top + layout.height, layout.left : layout.left + layout.width]
    x1, y1, x2, y2 = cell.bbox
    pad = 1 if min(x2 - x1, y2 - y1) > 4 else 0
    return crop[y1 + pad : y2 - pad, x1 + pad : x2 - pad]


def _seed_ocr_for_clusters(
    image: np.ndarray,
    layout: GridLayout,
    cells: List[CellRecord],
    per_cluster_limit: int = 6,
) -> None:
    grouped: Dict[int, List[CellRecord]] = defaultdict(list)
    for cell in cells:
        if not cell.is_empty:
            grouped[cell.cluster_id].append(cell)

    for items in grouped.values():
        ranked = sorted(
            items,
            key=lambda cell: (
                abs(cell.row - layout.rows / 2) + abs(cell.col - layout.cols / 2),
                cell.row,
                cell.col,
            ),
        )
        for cell in ranked[:per_cluster_limit]:
            patch = _cell_patch(image, layout, cell)
            cell.raw_symbol, cell.raw_confidence = _ocr_variants(patch)


def _assign_symbols(cells: List[CellRecord], use_cluster_consensus: bool) -> None:
    if not use_cluster_consensus:
        for cell in cells:
            if cell.is_empty:
                cell.symbol = ""
                cell.confidence = 1.0
            else:
                cell.symbol = cell.raw_symbol or "?"
                cell.confidence = cell.raw_confidence
        return

    grouped: Dict[int, List[CellRecord]] = defaultdict(list)
    for cell in cells:
        if not cell.is_empty:
            grouped[cell.cluster_id].append(cell)

    cluster_symbol: Dict[int, Tuple[str, float]] = {}
    for cluster_id, items in grouped.items():
        weighted: Dict[str, float] = defaultdict(float)
        for item in items:
            if item.raw_symbol:
                weighted[item.raw_symbol] += max(0.1, item.raw_confidence)
        if weighted:
            symbol, score = max(weighted.items(), key=lambda item: item[1])
            cluster_symbol[cluster_id] = (symbol, min(1.0, score / max(1, len(items))))
        else:
            cluster_symbol[cluster_id] = (f"C{cluster_id:02d}", 0.15)

    for cell in cells:
        if cell.is_empty:
            cell.symbol = ""
            cell.confidence = 1.0
            continue
        symbol, cluster_confidence = cluster_symbol[cell.cluster_id]
        if cell.raw_symbol and cell.raw_confidence >= 0.65:
            cell.symbol = cell.raw_symbol
            cell.confidence = max(cell.raw_confidence, cluster_confidence)
        else:
            cell.symbol = symbol
            cell.confidence = cluster_confidence


def assign_cells_from_legend(cells: list[CellRecord], legend: dict[str, LegendEntry]) -> None:
    legend_entries = list(legend.values())
    if not legend_entries:
        raise ValueError("legend-constrained assignment requires at least one legend entry")

    for cell in cells:
        if cell.is_empty:
            cell.symbol = ""
            cell.confidence = 1.0
            continue

        nearest = min(
            legend_entries,
            key=lambda entry: math.dist(cell.color_bgr, entry.color_bgr),
        )
        distance = math.dist(cell.color_bgr, nearest.color_bgr)
        cell.symbol = nearest.symbol
        cell.confidence = max(0.0, 1.0 - distance / (255.0 * math.sqrt(3)))


def _collect_neighbors(cell: CellRecord, index: dict[tuple[int, int], CellRecord]) -> list[CellRecord]:
    neighbors: list[CellRecord] = []
    for row_offset, col_offset in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        neighbor = index.get((cell.row + row_offset, cell.col + col_offset))
        if neighbor is not None:
            neighbors.append(neighbor)
    return neighbors


def _collect_weighted_neighbor_votes(cell: CellRecord, index: dict[tuple[int, int], CellRecord]) -> dict[str, float]:
    votes: dict[str, float] = defaultdict(float)
    offsets = [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, 0.6),
        (-1, 1, 0.6),
        (1, -1, 0.6),
        (1, 1, 0.6),
    ]
    for row_offset, col_offset, weight in offsets:
        neighbor = index.get((cell.row + row_offset, cell.col + col_offset))
        if neighbor is None or neighbor.is_empty or not neighbor.symbol:
            continue
        votes[neighbor.symbol] += weight
    return votes


def _border_band_width(layout: GridLayout) -> int:
    return max(2, min(5, math.ceil(layout.cols * 0.08)))


def _has_thin_contour_break(cell: CellRecord, index: dict[tuple[int, int], CellRecord]) -> bool:
    left = index.get((cell.row, cell.col - 1))
    right = index.get((cell.row, cell.col + 1))
    up = index.get((cell.row - 1, cell.col))
    down = index.get((cell.row + 1, cell.col))
    direct_neighbors = [neighbor for neighbor in (left, right, up, down) if neighbor is not None and not neighbor.is_empty]
    direct_votes: dict[str, int] = defaultdict(int)
    for neighbor in direct_neighbors:
        direct_votes[neighbor.symbol] += 1

    horizontal_bridge = (
        left is not None
        and right is not None
        and not left.is_empty
        and not right.is_empty
        and left.symbol == right.symbol
        and cell.symbol != left.symbol
    )
    vertical_bridge = (
        up is not None
        and down is not None
        and not up.is_empty
        and not down.is_empty
        and up.symbol == down.symbol
        and cell.symbol != up.symbol
    )
    strong_cross_outlier = any(count >= 3 and symbol != cell.symbol for symbol, count in direct_votes.items())
    return horizontal_bridge or vertical_bridge or strong_cross_outlier


def _pick_stabilized_symbol(
    cell: CellRecord,
    index: dict[tuple[int, int], CellRecord],
    legend: dict[str, LegendEntry],
    risk_flags: dict[str, bool],
) -> str:
    votes = {symbol: weight for symbol, weight in _collect_weighted_neighbor_votes(cell, index).items() if symbol in legend}
    if not votes:
        return cell.symbol

    candidate_symbol, candidate_support = max(votes.items(), key=lambda item: (item[1], item[0]))
    current_support = votes.get(cell.symbol, 0.0)
    if candidate_symbol == cell.symbol:
        return cell.symbol

    strong_consensus = candidate_support >= 2.5 and candidate_support >= current_support + 1.5
    if not strong_consensus:
        return cell.symbol

    if risk_flags["thin_contour"]:
        return candidate_symbol
    if risk_flags["first_three_rows"] and candidate_support >= 3.0:
        return candidate_symbol
    if risk_flags["border_region"] and candidate_support >= 2.5:
        return candidate_symbol
    return cell.symbol


def score_cell_confidence(cell: CellRecord, neighbors: list[CellRecord], risk_flags: dict[str, bool]) -> float:
    if cell.is_empty:
        return 1.0

    score = cell.confidence
    comparable = [neighbor for neighbor in neighbors if not neighbor.is_empty]
    if comparable:
        matching = sum(1 for neighbor in comparable if neighbor.symbol == cell.symbol)
        if matching == 0:
            score -= 0.08
        else:
            score += 0.05 * (matching / len(comparable))

    if risk_flags.get("first_three_rows"):
        score -= 0.22
    if risk_flags.get("border_region"):
        score -= 0.12
    if risk_flags.get("thin_contour"):
        score -= 0.24

    return max(0.0, min(1.0, score))


def smooth_high_risk_regions(cells: list[CellRecord], legend: dict[str, LegendEntry], layout: GridLayout) -> None:
    index = {(cell.row, cell.col): cell for cell in cells}
    original_symbols = {(cell.row, cell.col): cell.symbol for cell in cells}
    risk_by_cell: dict[tuple[int, int], dict[str, bool]] = {}
    replacement_by_cell: dict[tuple[int, int], str] = {}
    border_band = _border_band_width(layout)

    for cell in cells:
        if cell.is_empty:
            cell.high_risk = False
            continue

        border_region = cell.col <= border_band or cell.col > layout.cols - border_band
        risk_flags = {
            "first_three_rows": cell.row <= 3,
            "border_region": border_region,
            "thin_contour": _has_thin_contour_break(cell, index),
        }
        key = (cell.row, cell.col)
        risk_by_cell[key] = risk_flags
        replacement_by_cell[key] = _pick_stabilized_symbol(cell, index, legend, risk_flags)

    for cell in cells:
        if cell.is_empty:
            continue
        key = (cell.row, cell.col)
        replacement_symbol = replacement_by_cell[key]
        cell.high_risk = any(risk_by_cell[key].values())
        if replacement_symbol != cell.symbol:
            cell.symbol = replacement_symbol
            cell.needs_review = True

    stabilized_index = {(cell.row, cell.col): cell for cell in cells}
    for cell in cells:
        if cell.is_empty:
            continue
        key = (cell.row, cell.col)
        risk_flags = dict(risk_by_cell[key])
        risk_flags["stabilized"] = cell.symbol != original_symbols[key]
        neighbors = _collect_neighbors(cell, stabilized_index)
        cell.confidence = score_cell_confidence(cell, neighbors, risk_flags)
        if cell.high_risk:
            cell.needs_review = True


def _mark_review_cells(cells: List[CellRecord]) -> None:
    for cell in cells:
        if cell.is_empty:
            cell.needs_review = False
            continue
        weak_symbol = cell.symbol == "?" or cell.symbol.startswith("C")
        weak_confidence = cell.confidence < 0.55
        cell.needs_review = cell.high_risk or weak_symbol or weak_confidence


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _render_preview(layout: GridLayout, cells: List[CellRecord], output_path: Path, show_review: bool) -> None:
    margin = max(36, layout.cell_size * 3)
    canvas = Image.new(
        "RGB",
        (layout.cols * layout.cell_size + margin * 2, layout.rows * layout.cell_size + margin * 2),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = _font(max(10, int(layout.cell_size * 0.62)))
    index_font = _font(max(10, int(layout.cell_size * 0.7)))

    for cell in cells:
        x = margin + (cell.col - 1) * layout.cell_size
        y = margin + (cell.row - 1) * layout.cell_size
        fill = (255, 255, 255) if cell.is_empty else (cell.color_bgr[2], cell.color_bgr[1], cell.color_bgr[0])
        draw.rectangle([x, y, x + layout.cell_size, y + layout.cell_size], fill=fill)
        if cell.symbol:
            text_box = draw.textbbox((0, 0), cell.symbol, font=font)
            tw = text_box[2] - text_box[0]
            th = text_box[3] - text_box[1]
            luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
            text_color = "black" if luminance > 150 else "white"
            draw.text(
                (x + (layout.cell_size - tw) / 2, y + (layout.cell_size - th) / 2 - 1),
                cell.symbol,
                font=font,
                fill=text_color,
            )
        if show_review and cell.needs_review:
            draw.rectangle([x + 1, y + 1, x + layout.cell_size - 1, y + layout.cell_size - 1], outline="#D90429", width=2)

    for idx in range(layout.cols + 1):
        x = margin + idx * layout.cell_size
        width = 2 if idx % 10 == 0 else 1
        draw.line([x, margin, x, margin + layout.rows * layout.cell_size], fill="#444444", width=width)
    for idx in range(layout.rows + 1):
        y = margin + idx * layout.cell_size
        width = 2 if idx % 10 == 0 else 1
        draw.line([margin, y, margin + layout.cols * layout.cell_size, y], fill="#444444", width=width)

    for idx in range(layout.cols):
        label = str(idx + 1)
        x = margin + idx * layout.cell_size + layout.cell_size / 2
        box = draw.textbbox((0, 0), label, font=index_font)
        draw.text((x - (box[2] - box[0]) / 2, margin - box[3] - 6), label, fill="#111111", font=index_font)
    for idx in range(layout.rows):
        label = str(idx + 1)
        y = margin + idx * layout.cell_size + layout.cell_size / 2
        box = draw.textbbox((0, 0), label, font=index_font)
        draw.text((margin - (box[2] - box[0]) - 8, y - (box[3] - box[1]) / 2), label, fill="#111111", font=index_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def _write_csv(cells: Iterable[CellRecord], output_path: Path, include_review: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["row", "col", "symbol", "color_hex", "cluster_id", "empty", "confidence"]
        if include_review:
            fieldnames.append("needs_review")
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for cell in cells:
            row = {
                "row": cell.row,
                "col": cell.col,
                "symbol": cell.symbol,
                "color_hex": cell.color_hex,
                "cluster_id": cell.cluster_id,
                "empty": int(cell.is_empty),
                "confidence": f"{cell.confidence:.3f}",
            }
            if include_review:
                row["needs_review"] = int(cell.needs_review)
            writer.writerow(row)


def write_legend_csv(entries: list[LegendEntry], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "color_hex", "confidence", "x1", "y1", "x2", "y2"])
        writer.writeheader()
        for entry in entries:
            x1, y1, x2, y2 = entry.bbox
            writer.writerow(
                {
                    "symbol": entry.symbol,
                    "color_hex": "#{:02X}{:02X}{:02X}".format(
                        entry.color_bgr[2], entry.color_bgr[1], entry.color_bgr[0]
                    ),
                    "confidence": f"{entry.confidence:.3f}",
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )


def generate_reference_outputs(image_path: Path | str, output_root: Path | str) -> Dict[str, Dict[str, Path]]:
    image_path = Path(image_path)
    output_root = Path(output_root)
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)

    layout = detect_grid_layout(image)
    base_cells = _extract_cells(image, layout)
    _cluster_cells(base_cells)
    _seed_ocr_for_clusters(image, layout, base_cells)
    cluster_legend_entries = _derive_legend_entries_from_clusters(base_cells)
    legend_entries = _choose_legend_entries(
        extract_legend_entries(image, layout),
        cluster_legend_entries,
    )
    legend_table = build_legend_table(legend_entries)

    outputs: Dict[str, Dict[str, Path]] = {}
    variants = {
        "approach_1": {"consensus": False, "review": False},
        "approach_2": {"consensus": True, "review": False},
        "approach_3": {"consensus": True, "review": True},
    }
    for name, options in variants.items():
        cells = [
            CellRecord(
                row=cell.row,
                col=cell.col,
                bbox=cell.bbox,
                color_bgr=cell.color_bgr,
                color_hex=cell.color_hex,
                is_empty=cell.is_empty,
                raw_symbol=cell.raw_symbol,
                raw_confidence=cell.raw_confidence,
                cluster_id=cell.cluster_id,
                high_risk=cell.high_risk,
            )
            for cell in base_cells
        ]
        if options["consensus"]:
            assign_cells_from_legend(cells, legend_table)
        else:
            _assign_symbols(cells, use_cluster_consensus=False)
        if options["review"]:
            smooth_high_risk_regions(cells, legend_table, layout)
            _mark_review_cells(cells)

        variant_dir = output_root / name
        preview_path = variant_dir / "preview.png"
        csv_path = variant_dir / "grid.csv"
        _render_preview(layout, cells, preview_path, show_review=options["review"])
        _write_csv(cells, csv_path, include_review=options["review"])
        if name == "approach_2":
            write_legend_csv(legend_entries, variant_dir / "legend.csv")
        outputs[name] = {"preview": preview_path, "csv": csv_path}
    return outputs


def generate_web_result(image_path: Path | str, workdir: Path | str) -> dict:
    outputs = generate_reference_outputs(image_path, workdir)
    return build_web_export_payload(outputs, image_path=image_path, workdir=workdir)


def main() -> None:
    root = Path(__file__).resolve().parent
    outputs = generate_reference_outputs(root / "blur.JPG", root / "outputs")
    for name, files in outputs.items():
        print(name, files["preview"], files["csv"])


if __name__ == "__main__":
    main()
