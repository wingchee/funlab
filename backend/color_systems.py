import copy
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


COLOR_SYSTEMS = ("MARD",)
_MAPPING_PATH = Path(__file__).with_name("color_system_mapping.json")


@lru_cache(maxsize=1)
def _load_mapping() -> dict[str, dict[str, str]]:
    return json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _indexed_colors() -> tuple[tuple[str, tuple[int, int, int], dict[str, str]], ...]:
    indexed = []
    for hex_value, codes in _load_mapping().items():
        indexed.append((hex_value.upper(), _hex_to_rgb(hex_value), codes))
    return tuple(indexed)


def _normalize_system(color_system: Optional[str]) -> str:
    if str(color_system or "").upper() == "MARD":
        return "MARD"
    return "MARD"


def _normalize_hex(hex_value: Any) -> str:
    raw = str(hex_value or "").strip().upper()
    if raw and not raw.startswith("#"):
        raw = f"#{raw}"
    if len(raw) == 7:
        try:
            int(raw[1:], 16)
            return raw
        except ValueError:
            pass
    return "#FFFFFF"


def _hex_to_rgb(hex_value: str) -> tuple[int, int, int]:
    normalized = _normalize_hex(hex_value)
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def _distance_sq(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.pow(a[0] - b[0], 2) + math.pow(a[1] - b[1], 2) + math.pow(a[2] - b[2], 2)


def nearest_bead_color(hex_value: str, color_system: str) -> dict[str, str]:
    """Return the nearest mapped bead color from the MARD 221-color palette."""
    selected = _normalize_system(color_system)
    target = _hex_to_rgb(hex_value)
    best_hex = "#FFFFFF"
    best_codes: dict[str, str] = {}
    best_distance = float("inf")

    for mapped_hex, rgb, codes in _indexed_colors():
        distance = _distance_sq(target, rgb)
        if distance < best_distance:
            best_hex = mapped_hex
            best_codes = codes
            best_distance = distance
            if distance == 0:
                break

    bead_id = best_codes.get(selected) or best_codes.get("MARD") or best_hex
    return {"id": bead_id, "name": bead_id, "hex": best_hex}


def apply_color_system_to_result(result: dict[str, Any], color_system: str) -> dict[str, Any]:
    """Snap processing_result colors to the selected bead system and rewrite symbols."""
    selected = _normalize_system(color_system)
    mapped = copy.deepcopy(result)
    legend = mapped.get("legend") or []
    cells = mapped.get("cells") or []

    symbol_to_bead: dict[str, dict[str, str]] = {}
    ordered_beads: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for entry in legend:
        source_symbol = str(entry.get("symbol") or "")
        bead = nearest_bead_color(entry.get("color_hex", "#FFFFFF"), selected)
        if source_symbol:
            symbol_to_bead[source_symbol] = bead
        if bead["id"] not in seen_ids:
            ordered_beads.append(bead)
            seen_ids.add(bead["id"])

    for cell in cells:
        if cell.get("empty", False) or not cell.get("symbol"):
            cell["symbol"] = ""
            cell["color_hex"] = "#FFFFFF"
            continue
        bead = symbol_to_bead.get(str(cell.get("symbol")))
        if bead is None:
            bead = nearest_bead_color(cell.get("color_hex", "#FFFFFF"), selected)
            symbol_to_bead[str(cell.get("symbol"))] = bead
            if bead["id"] not in seen_ids:
                ordered_beads.append(bead)
                seen_ids.add(bead["id"])
        cell["symbol"] = bead["id"]
        cell["color_hex"] = bead["hex"]

    mapped["legend"] = [
        {
            "symbol": bead["id"],
            "color_hex": bead["hex"],
            "confidence": 1.0,
            "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
            "name": bead["name"],
        }
        for bead in ordered_beads
    ]
    mapped["palette_name"] = selected
    return mapped
