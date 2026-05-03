from pydantic import BaseModel
from typing import List, Any


class UserCreate(BaseModel):
    email: str
    password: str
    name: str = ""


class UserLogin(BaseModel):
    email: str
    password: str


class PublishRequest(BaseModel):
    title: str
    tags: List[str]
    size: str
    processing_result: dict


class TableTimerSetRequest(BaseModel):
    elapsed_seconds: int
    is_running: bool = False
