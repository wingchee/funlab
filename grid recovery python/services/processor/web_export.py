from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from ._repo_imports import load_repo_module


def build_grid_payload(image_path: Union[Path, str], workdir: Union[Path, str]) -> dict[str, Any]:
    grid_recovery = load_repo_module("grid_recovery")
    return grid_recovery.generate_web_result(image_path, workdir)
