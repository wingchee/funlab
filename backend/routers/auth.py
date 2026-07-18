import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from auth import (
    create_token,
    get_current_user,
    hash_password,
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


@router.put("/profile")
def update_profile(
    body: schemas.ProfileUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    has_email_update = body.email != ""
    has_password_update = body.new_password != ""
    if has_email_update == has_password_update:
        raise HTTPException(status_code=400, detail="Provide exactly one profile update")

    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid current password")

    if has_email_update:
        email = normalize_email(body.email)
        if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HTTPException(status_code=400, detail="A valid email is required")
        existing_user = (
            db.query(models.User.id)
            .filter(func.lower(func.trim(models.User.email)) == email)
            .filter(models.User.id != current_user.id)
            .first()
        )
        if existing_user:
            db.rollback()
            raise HTTPException(status_code=409, detail="Email is already in use")
        current_user.email = email
    elif len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    else:
        current_user.password_hash = hash_password(body.new_password)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already in use") from exc
    db.refresh(current_user)
    return serialize_account(current_user)
