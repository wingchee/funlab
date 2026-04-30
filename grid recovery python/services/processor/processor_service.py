from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from .blob_client import download_image_url, ensure_workdir
from .web_export import build_grid_payload


class ProcessRequest(BaseModel):
    image_path: Optional[str] = None
    image_url: Optional[str] = None
    workdir: Optional[str] = None

    @model_validator(mode="after")
    def validate_image_source(self) -> "ProcessRequest":
        if self.image_path or self.image_url:
            return self

        raise ValueError("image_path or image_url is required")


class ProcessResponse(BaseModel):
    image: dict[str, Any] = Field(default_factory=dict)
    rows: int
    cols: int
    cells: list[dict[str, Any]]
    legend: list[dict[str, Any]]
    artifacts: dict[str, Any]


def process_image(request: ProcessRequest) -> ProcessResponse:
    workdir = ensure_workdir(request.workdir)
    image_path = resolve_image_path(request, workdir)
    payload = build_grid_payload(image_path, workdir)
    return ProcessResponse(**payload)


def resolve_image_path(request: ProcessRequest, workdir: Path) -> Path:
    if request.image_path is not None:
        return Path(request.image_path)

    if request.image_url is not None:
        return download_image_url(request.image_url, workdir)

    raise ValueError("image_path or image_url is required")
