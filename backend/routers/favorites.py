import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db

router = APIRouter()


def _serialize(p: models.Pattern) -> dict:
    return {
        "id": p.id,
        "title": p.title,
        "tags": json.loads(p.tags),
        "size": p.size,
        "grid_w": p.grid_w,
        "grid_h": p.grid_h,
        "faves_count": p.faves_count,
        "preview_color": p.preview_color,
        "palette": json.loads(p.palette),
        "grid_data": json.loads(p.grid_data),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("")
def list_favorites(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Favorite).filter(models.Favorite.user_id == current_user.id).all()
    return [_serialize(r.pattern) for r in rows]


@router.get("/ids")
def list_favorite_ids(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Favorite).filter(models.Favorite.user_id == current_user.id).all()
    return [r.pattern_id for r in rows]


@router.post("/{pattern_id}")
def toggle_favorite(
    pattern_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pattern = db.query(models.Pattern).filter(models.Pattern.id == pattern_id).first()
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    existing = db.query(models.Favorite).filter(
        models.Favorite.user_id == current_user.id,
        models.Favorite.pattern_id == pattern_id,
    ).first()

    if existing:
        db.delete(existing)
        pattern.faves_count = max(0, pattern.faves_count - 1)
        db.commit()
        return {"favorited": False, "faves_count": pattern.faves_count}

    db.add(models.Favorite(user_id=current_user.id, pattern_id=pattern_id))
    pattern.faves_count += 1
    db.commit()
    return {"favorited": True, "faves_count": pattern.faves_count}
