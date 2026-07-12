from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import schemas
from auth import (
    create_token,
    get_current_user,
    normalize_email,
    normalize_phone,
    verify_password,
)
from database import get_db

router = APIRouter()


def serialize_account(user: models.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": bool(user.is_admin),
        "member_code": user.member_code,
        "phone": user.phone,
        "is_active": bool(user.is_active),
        "account_type": "member" if user.member_code else "user",
    }


@router.post("/login")
def login(body: schemas.AccountLogin, db: Session = Depends(get_db)):
    identifier = body.identifier.strip()
    active_users = db.query(models.User).filter(models.User.is_active.is_(True))
    user = active_users.filter(
        func.lower(func.trim(models.User.email)) == normalize_email(identifier)
    ).first()
    if user is None:
        phone = normalize_phone(identifier)
        if phone:
            user = active_users.filter(models.User.phone == phone).first()
    if user is None:
        user = active_users.filter(models.User.member_code.ilike(identifier)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {
        "access_token": create_token(user.id),
        "token_type": "bearer",
        "user": serialize_account(user),
    }


@router.get("/me")
def me(current_user: models.User = Depends(get_current_user)):
    return serialize_account(current_user)
