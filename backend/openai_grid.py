import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_DEFAULT_COLORS = [
    "#F47A8A",
    "#6BB5E8",
    "#F5C518",
    "#2E7D32",
    "#F5F5F0",
    "#1C1C1E",
    "#FFAB76",
    "#9B72CF",
    "#FF6B6B",
    "#26A69A",
    "#8D6E63",
    "#7E57C2",
]

OPENAI_GRID_PROMPT = """Create a JSON bead grid for Perler/Hama 拼豆 from the image.

Requirements:
- If a second image is supplied, treat it as the original reference image. Use it to recover the true subject shape, pose, accessories, and distinctive colors that may have been lost in the edited craft image.
- Return only the main craft subject, using blank cells for background.
- Use simple flat bead colors, clear outline shapes, and no text or labels inside the grid.
- Preserve the subject's full silhouette, important accessories, recognizable markings, and dominant colors.
- Keep the grid within the requested size. Use fewer rows or columns if needed to preserve aspect ratio.
- Prefer 6 to 14 bead colors unless the subject genuinely needs more.
- Add a clean outline where it improves readability, but do not make every edge heavy.
- Remove isolated noisy beads, background residue, random speckles, and thin details that would be hard to build.
- Use blank/background cells around the subject instead of filling the whole grid.
- Use short symbols such as A, B, C for bead colors. Use an empty string for blank/background cells.
- Palette hex values must be six-digit #RRGGBB colors.
"""


class OpenAIGridPaletteEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Short bead symbol used in the grid, for example A")
    name: str = Field(description="Human-readable color name")
    hex: str = Field(description="Six-digit #RRGGBB color")


class OpenAIGridResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: int = Field(description="Number of grid rows")
    cols: int = Field(description="Number of grid columns")
    palette: list[OpenAIGridPaletteEntry]
    grid: list[list[str]] = Field(
        description="2-D array of palette ids; use an empty string for blank/background cells"
    )


def _parse_grid_size(grid_size: str) -> tuple[int, int]:
    try:
        w_str, h_str = grid_size.lower().split("x", 1)
        return int(w_str), int(h_str)
    except Exception as exc:
        raise ValueError(f"Invalid grid size: {grid_size}") from exc


def _clean_symbol(value: Any) -> str:
    symbol = str(value or "").strip()
    if not symbol or symbol in {".", "-", "_", "0", "None", "null"}:
        return ""
    return symbol[:8]


def _clean_hex(value: Any, fallback_index: int = 0) -> str:
    raw = str(value or "").strip().upper()
    if raw and not raw.startswith("#"):
        raw = f"#{raw}"
    if len(raw) == 7:
        try:
            int(raw[1:], 16)
            return raw
        except ValueError:
            pass
    return _DEFAULT_COLORS[fallback_index % len(_DEFAULT_COLORS)]


def _coerce_raw_grid(raw_grid: Any) -> dict[str, Any]:
    if isinstance(raw_grid, OpenAIGridResponse):
        return raw_grid.model_dump()
    if isinstance(raw_grid, BaseModel):
        return raw_grid.model_dump()
    if isinstance(raw_grid, str):
        return json.loads(raw_grid)
    if isinstance(raw_grid, dict):
        return raw_grid
    raise ValueError("OpenAI grid response must be a dict, JSON string, or Pydantic model")


def normalize_openai_grid(
    raw_grid: Any,
    *,
    source_name: str,
    requested_size: str,
    ai_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convert OpenAI's structured grid JSON into PixelCraft's processing_result shape."""
    data = _coerce_raw_grid(raw_grid)
    max_cols, max_rows = _parse_grid_size(requested_size)
    raw_rows = data.get("grid") or []
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("OpenAI grid response did not include grid rows")

    normalized_grid: list[list[str]] = []
    for row in raw_rows[:max_rows]:
        if not isinstance(row, list):
            raise ValueError("OpenAI grid rows must be arrays")
        normalized_grid.append([_clean_symbol(cell) for cell in row[:max_cols]])

    rows = len(normalized_grid)
    cols = max((len(row) for row in normalized_grid), default=0)
    if rows < 1 or cols < 1:
        raise ValueError("OpenAI grid response produced an empty grid")
    cols = min(cols, max_cols)

    for row in normalized_grid:
        row.extend([""] * (cols - len(row)))
        del row[cols:]

    palette_by_symbol: dict[str, dict[str, str]] = {}
    for idx, entry in enumerate(data.get("palette") or []):
        if not isinstance(entry, dict):
            continue
        symbol = _clean_symbol(entry.get("id") or entry.get("symbol"))
        if not symbol:
            continue
        palette_by_symbol[symbol] = {
            "id": symbol,
            "name": str(entry.get("name") or symbol).strip() or symbol,
            "hex": _clean_hex(entry.get("hex") or entry.get("color_hex"), idx),
        }

    used_symbols = []
    for row in normalized_grid:
        for symbol in row:
            if symbol and symbol not in used_symbols:
                used_symbols.append(symbol)

    for symbol in used_symbols:
        if symbol not in palette_by_symbol:
            palette_by_symbol[symbol] = {
                "id": symbol,
                "name": symbol,
                "hex": _clean_hex(None, len(palette_by_symbol)),
            }

    ordered_palette = [palette_by_symbol[symbol] for symbol in used_symbols]
    legend = [
        {
            "symbol": entry["id"],
            "color_hex": entry["hex"],
            "confidence": 0.85,
            "bbox": {"x1": 0, "y1": 0, "x2": 0, "y2": 0},
            "name": entry["name"],
        }
        for entry in ordered_palette
    ]

    cells = []
    for row_idx, row in enumerate(normalized_grid, start=1):
        for col_idx, symbol in enumerate(row, start=1):
            palette_entry = palette_by_symbol.get(symbol)
            is_empty = not symbol
            cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "symbol": "" if is_empty else symbol,
                    "color_hex": "#FFFFFF" if is_empty else palette_entry["hex"],
                    "cluster_id": -1 if is_empty else used_symbols.index(symbol),
                    "empty": is_empty,
                    "confidence": 0.85,
                    "needs_review": False,
                }
            )

    return {
        "rows": rows,
        "cols": cols,
        "cells": cells,
        "legend": legend,
        "artifacts": {},
        "image": {"source_name": source_name},
        "ai_enhancement": ai_metadata or {},
        "ai_grid": {
            "attempted": True,
            "used": True,
            "provider": "openai",
            "requested_size": requested_size,
        },
    }


def _image_to_data_url(image_path: str) -> str:
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        mime_type = "image/png"
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _provider_error_metadata(exc: Exception) -> dict[str, Any]:
    raw = str(exc)
    lowered = raw.lower()
    if "refusal" in lowered or "safety" in lowered or "moderation" in lowered:
        error_type = "safety_blocked"
    else:
        error_type = "provider_error"
    return {"error_type": error_type, "reason": raw, "provider_error": raw}


def generate_openai_bead_grid(
    image_path: str,
    *,
    grid_size: str,
    quality: int,
    ai_metadata: Optional[dict[str, Any]] = None,
    current_grid_json: Optional[str] = None,
    original_image_path: Optional[str] = None,
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Ask OpenAI vision for a bead-grid JSON payload and normalize it for publishing."""
    metadata: dict[str, Any] = {
        "attempted": True,
        "used": False,
        "provider": "openai",
        "model": os.getenv("OPENAI_GRID_MODEL", "gpt-4.1-mini"),
        "requested_size": grid_size,
    }

    if os.getenv("PIXELCRAFT_DISABLE_AI_GRID", "").lower() in {"1", "true", "yes"}:
        metadata["reason"] = "disabled"
        return None, metadata

    if not os.getenv("OPENAI_API_KEY"):
        metadata["reason"] = "OPENAI_API_KEY is not set"
        return None, metadata

    try:
        from openai import OpenAI
    except ImportError:
        metadata["reason"] = "openai package is not installed"
        return None, metadata

    try:
        max_cols, max_rows = _parse_grid_size(grid_size)
        base_url = os.getenv("OPENAI_BASE_URL") or None
        timeout = float(os.getenv("OPENAI_REQUEST_TIMEOUT", "45"))
        client = OpenAI(base_url=base_url, timeout=timeout) if base_url else OpenAI(timeout=timeout)
        data_url = _image_to_data_url(image_path)
        prompt = (
            f"Create a JSON bead grid for this image with at most {max_cols} columns "
            f"and {max_rows} rows. Color accuracy target: {quality} out of 100."
        )
        if current_grid_json:
            prompt += (
                "\nUse this current editor grid JSON as reference context. Preserve useful "
                "manual edits, simplify noisy regions, and return a complete improved grid "
                f"for the image:\n{current_grid_json[:12000]}"
            )
            metadata["current_grid_reference_used"] = True
        content: list[dict[str, str]] = [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": data_url, "detail": "high"},
        ]
        if original_image_path and os.path.abspath(original_image_path) != os.path.abspath(image_path):
            content.append(
                {
                    "type": "input_image",
                    "image_url": _image_to_data_url(original_image_path),
                    "detail": "high",
                }
            )
            metadata["original_reference_image_used"] = True
        response = client.responses.parse(
            model=metadata["model"],
            instructions=OPENAI_GRID_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            text_format=OpenAIGridResponse,
            max_output_tokens=int(os.getenv("OPENAI_GRID_MAX_OUTPUT_TOKENS", "60000")),
        )

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            output_text = getattr(response, "output_text", None)
            if not output_text:
                raise ValueError("OpenAI grid response did not include structured output")
            parsed = json.loads(output_text)

        metadata["used"] = True
        result = normalize_openai_grid(
            parsed,
            source_name=os.path.basename(image_path),
            requested_size=grid_size,
            ai_metadata=ai_metadata or metadata,
        )
        result["ai_grid"] = metadata
        return result, metadata
    except Exception as exc:
        logger.warning("OpenAI bead grid JSON generation failed: %s", exc)
        metadata.update(_provider_error_metadata(exc))
        return None, metadata
