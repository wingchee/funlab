from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI
from fastapi import Header, HTTPException

from . import processor_service
from .processor_service import ProcessRequest, ProcessResponse


app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/process", response_model=ProcessResponse)
def process_image(
    request: ProcessRequest,
    x_internal_token: Optional[str] = Header(default=None),
) -> ProcessResponse:
    shared_secret = os.getenv("PROCESSOR_SHARED_SECRET")

    if shared_secret and x_internal_token != shared_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return processor_service.process_image(request)
