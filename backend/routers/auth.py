import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_
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


def _generate_member_code(db: Session) -> str:
    for _ in range(20):
        code = f"FL{secrets.randbelow(100_000_000):08d}"
        if not db.query(models.User.id).filter(models.User.member_code == code).first():
            return code
    raise HTTPException(status_code=500, detail="Unable to generate unique Member ID")


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


@router.post("/register")
def register(body: schemas.MemberRegistration, db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    name = body.name.strip()
    phone = normalize_phone(body.phone)
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone is required")
    if not body.password:
        raise HTTPException(status_code=400, detail="Password is required")
    if body.password != body.password_confirmation:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if db.query(models.User.id).filter(models.User.email.ilike(email)).first():
        raise HTTPException(status_code=409, detail="An account already exists for this email")
    if db.query(models.User.id).filter(models.User.phone == phone).first():
        raise HTTPException(status_code=409, detail="An account already exists for this phone")
    user = models.User(
        email=email,
        password_hash=hash_password(body.password),
        name=name,
        is_admin=False,
        member_code=_generate_member_code(db),
        phone=phone,
        is_active=True,
        notes="",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account already exists") from exc
    db.refresh(user)
    return {
        "access_token": create_token(user.id),
        "token_type": "bearer",
        "user": serialize_account(user),
    }


@router.post("/login")
def login(body: schemas.AccountLogin, db: Session = Depends(get_db)):
    identifier = body.identifier.strip()
    user = (
        db.query(models.User)
        .filter(
            or_(
                func.lower(func.trim(models.User.email)) == normalize_email(identifier),
                models.User.phone == normalize_phone(identifier),
                models.User.member_code.ilike(identifier),
            ),
            models.User.is_active.is_(True),
        )
        .first()
    )
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
