from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import models
import schemas
from auth import verify_password, create_token, get_current_user
from database import get_db

router = APIRouter()


def _user_dict(user: models.User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "is_admin": user.is_admin}


@router.post("/register")
def register(_body: schemas.UserCreate, _db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Registration is temporarily disabled",
    )


@router.post("/login")
def login(body: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"access_token": create_token(user.id), "token_type": "bearer", "user": _user_dict(user)}


@router.get("/me")
def me(current_user: models.User = Depends(get_current_user)):
    return _user_dict(current_user)
