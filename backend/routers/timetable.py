from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_admin_user
from database import get_db

router = APIRouter()
TABLE_COUNT = 8


def _current_elapsed_seconds(timer: models.TableTimer, now: datetime) -> int:
    elapsed = max(0, int(timer.elapsed_seconds or 0))
    if timer.is_running and timer.started_at:
        elapsed += max(0, int((now - timer.started_at).total_seconds()))
    return elapsed


def _serialize(timer: models.TableTimer, now: Optional[datetime] = None) -> dict:
    current = now or datetime.utcnow()
    elapsed = _current_elapsed_seconds(timer, current)
    return {
        "id": timer.id,
        "table_number": timer.table_number,
        "status": "Occupied" if timer.is_running else "Free",
        "is_running": bool(timer.is_running),
        "elapsed_seconds": elapsed,
        "started_at": timer.started_at.isoformat() if timer.started_at else None,
        "updated_at": timer.updated_at.isoformat() if timer.updated_at else None,
    }


def _ensure_table_timers(db: Session) -> None:
    existing = {
        row.table_number
        for row in db.query(models.TableTimer.table_number).all()
    }
    missing = [number for number in range(1, TABLE_COUNT + 1) if number not in existing]
    if not missing:
        return
    for number in missing:
        db.add(models.TableTimer(table_number=number, is_running=False, elapsed_seconds=0))
    db.commit()


def _get_table(db: Session, table_number: int) -> models.TableTimer:
    _ensure_table_timers(db)
    if table_number < 1 or table_number > TABLE_COUNT:
        raise HTTPException(status_code=404, detail="Table not found")
    timer = db.query(models.TableTimer).filter(models.TableTimer.table_number == table_number).first()
    if not timer:
        raise HTTPException(status_code=404, detail="Table not found")
    return timer


@router.get("")
def list_tables(db: Session = Depends(get_db)):
    _ensure_table_timers(db)
    now = datetime.utcnow()
    rows = db.query(models.TableTimer).order_by(models.TableTimer.table_number.asc()).all()
    return [_serialize(row, now=now) for row in rows]


@router.get("/{table_number}")
def get_table(table_number: int, db: Session = Depends(get_db)):
    return _serialize(_get_table(db, table_number), now=datetime.utcnow())


@router.post("/{table_number}/start")
def start_table(
    table_number: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    timer = _get_table(db, table_number)
    if not timer.is_running:
        timer.is_running = True
        timer.started_at = datetime.utcnow()
        db.commit()
        db.refresh(timer)
    return _serialize(timer, now=datetime.utcnow())


@router.post("/{table_number}/stop")
def stop_table(
    table_number: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    timer = _get_table(db, table_number)
    if timer.is_running:
        now = datetime.utcnow()
        timer.elapsed_seconds = _current_elapsed_seconds(timer, now)
        timer.is_running = False
        timer.started_at = None
        db.commit()
        db.refresh(timer)
    return _serialize(timer, now=datetime.utcnow())


@router.post("/{table_number}/reset")
def reset_table(
    table_number: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    timer = _get_table(db, table_number)
    timer.elapsed_seconds = 0
    timer.is_running = False
    timer.started_at = None
    db.commit()
    db.refresh(timer)
    return _serialize(timer, now=datetime.utcnow())


@router.put("/{table_number}")
def set_table(
    table_number: int,
    body: schemas.TableTimerSetRequest,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if body.elapsed_seconds < 0:
        raise HTTPException(status_code=400, detail="Elapsed seconds must be 0 or greater")
    timer = _get_table(db, table_number)
    timer.elapsed_seconds = int(body.elapsed_seconds)
    timer.is_running = bool(body.is_running)
    timer.started_at = datetime.utcnow() if timer.is_running else None
    db.commit()
    db.refresh(timer)
    return _serialize(timer, now=datetime.utcnow())
