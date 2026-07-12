import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db

router = APIRouter()


def _serialize(p: models.Pattern) -> dict:
    d = {
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
    return d


@router.get("")
def list_patterns(
    search: Optional[str] = Query(None),
    size: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(models.Pattern)
    if search:
        q = q.filter(
            models.Pattern.title.ilike(f"%{search}%") | models.Pattern.tags.ilike(f"%{search}%")
        )
    if size and size != "All":
        q = q.filter(models.Pattern.size == size)
    return [_serialize(p) for p in q.order_by(models.Pattern.created_at.desc()).all()]


@router.get("/{pattern_id}")
def get_pattern(pattern_id: int, db: Session = Depends(get_db)):
    p = db.query(models.Pattern).filter(models.Pattern.id == pattern_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return _serialize(p)


@router.delete("/{pattern_id}")
def delete_pattern(
    pattern_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    p = db.query(models.Pattern).filter(models.Pattern.id == pattern_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pattern not found")
    db.delete(p)
    db.commit()
    return {"ok": True}
