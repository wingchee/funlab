from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse
from urllib.request import urlopen


def ensure_workdir(workdir: Optional[Union[str, Path]] = None) -> Path:
    if workdir is None:
        return Path(tempfile.mkdtemp(prefix="grid-processor-"))

    resolved = Path(workdir)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def download_image_url(image_url: str, workdir: Union[str, Path]) -> Path:
    target_dir = ensure_workdir(workdir)
    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix or ".img"
    output_path = target_dir / f"source{suffix}"

    with urlopen(image_url) as response, output_path.open("wb") as handle:
        handle.write(response.read())

    return output_path
