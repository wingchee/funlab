from pydantic import BaseModel
from typing import List, Any, Optional


class UserCreate(BaseModel):
    email: str
    password: str
    name: str = ""


class AccountLogin(BaseModel):
    identifier: str
    password: str


class ProfileUpdate(BaseModel):
    current_password: str
    email: str = ""
    new_password: str = ""


class PublishRequest(BaseModel):
    title: str
    tags: List[str]
    size: str
    processing_result: dict


class TableTimerSetRequest(BaseModel):
    elapsed_seconds: int
    is_running: bool = False


class TableTimerStartRequest(BaseModel):
    member_code: str = ""


class TableMemberAttachRequest(BaseModel):
    member_code: str = ""


class MemberCreate(BaseModel):
    name: str
    phone: str


class MemberRegistration(BaseModel):
    email: str
    name: str
    phone: str
    password: str
    password_confirmation: str


class MemberUpdate(BaseModel):
    email: str = ""
    name: str = ""
    phone: str = ""
    password: str = ""
    is_active: Optional[bool] = None
    notes: str = ""


class MembershipPromotion(BaseModel):
    phone: str
    member_code: str = ""


class MemberPackageCreate(BaseModel):
    package_name: str = "10-hour package"
    total_seconds: int = 10 * 60 * 60
    notes: str = ""


class MemberPackageUpdate(BaseModel):
    package_name: str = ""
    remaining_seconds: Optional[int] = None
    total_seconds: Optional[int] = None
    notes: str = ""
