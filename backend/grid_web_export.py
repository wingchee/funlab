from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict


def _read_grid_cells(path: Path) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            cells.append(
                {
                    "row": int(row["row"]),
                    "col": int(row["col"]),
                    "symbol": row["symbol"],
                    "color_hex": row["color_hex"],
                    "cluster_id": int(row["cluster_id"]),
                    "empty": row["empty"] == "1",
                    "confidence": float(row["confidence"]),
                    "needs_review": row.get("needs_review", "0") == "1",
                }
            )
    return cells


def _read_legend(path: Path) -> list[dict[str, Any]]:
    legend: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            legend.append(
                {
                    "symbol": row["symbol"],
                    "color_hex": row["color_hex"],
                    "confidence": float(row["confidence"]),
                    "bbox": {
                        "x1": int(row["x1"]),
                        "y1": int(row["y1"]),
                        "x2": int(row["x2"]),
                        "y2": int(row["y2"]),
                    },
                }
            )
    return legend


def _artifact_metadata(path: Path, workdir: Path | None) -> dict[str, Any]:
    metadata = {
        "filename": path.name,
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    if workdir is not None:
        metadata["relative_path"] = str(path.relative_to(workdir))
    return metadata


def build_web_export_payload(
    outputs: Dict[str, Dict[str, Path]],
    *,
    image_path: Path | str | None = None,
    workdir: Path | str | None = None,
) -> dict[str, Any]:
    artifact_root = Path(workdir) if workdir is not None else None
    review_csv = outputs["approach_3"]["csv"]
    cells = _read_grid_cells(review_csv)
    legend_path = outputs["approach_2"]["csv"].with_name("legend.csv")
    legend = _read_legend(legend_path)

    payload = {
        "rows": max((cell["row"] for cell in cells), default=0),
        "cols": max((cell["col"] for cell in cells), default=0),
        "cells": cells,
        "legend": legend,
        "artifacts": {
            "approach_1": {
                name: _artifact_metadata(path, artifact_root) for name, path in outputs["approach_1"].items()
            },
            "approach_2": {
                **{name: _artifact_metadata(path, artifact_root) for name, path in outputs["approach_2"].items()},
                "legend": _artifact_metadata(legend_path, artifact_root),
            },
            "approach_3": {
                name: _artifact_metadata(path, artifact_root) for name, path in outputs["approach_3"].items()
            },
        },
    }
    if image_path is not None:
        payload["image"] = {"source_name": Path(image_path).name}
    return payload
