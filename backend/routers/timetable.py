from datetime import datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_admin_user
from database import get_db

router = APIRouter()
TABLE_COUNT = 8
FIRST_HOUR_SECONDS = 60 * 60
HALF_HOUR_SECONDS = 30 * 60
GRACE_SECONDS = 10 * 60


def calculate_charged_seconds(occupied_seconds: int) -> int:
    occupied = max(0, int(occupied_seconds or 0))
    if occupied == 0:
        return 0
    if occupied <= FIRST_HOUR_SECONDS:
        return FIRST_HOUR_SECONDS

    remaining = occupied - FIRST_HOUR_SECONDS
    charged_blocks = remaining // HALF_HOUR_SECONDS
    if remaining % HALF_HOUR_SECONDS > GRACE_SECONDS:
        charged_blocks += 1
    return FIRST_HOUR_SECONDS + (charged_blocks * HALF_HOUR_SECONDS)


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
        "charged_seconds": calculate_charged_seconds(elapsed),
    }


def _serialize_log(log: models.TableTimeLog) -> dict:
    return {
        "id": log.id,
        "table_number": log.table_number,
        "started_at": log.started_at.isoformat(),
        "ended_at": log.ended_at.isoformat(),
        "occupied_seconds": int(log.occupied_seconds or 0),
        "charged_seconds": int(log.charged_seconds or 0),
    }


def _record_time_log(
    db: Session,
    timer: models.TableTimer,
    started_at: Optional[datetime],
    ended_at: datetime,
    occupied_seconds: int,
) -> Optional[models.TableTimeLog]:
    occupied = max(0, int(occupied_seconds or 0))
    if occupied <= 0:
        return None
    log = models.TableTimeLog(
        table_number=timer.table_number,
        started_at=started_at or ended_at - timedelta(seconds=occupied),
        ended_at=ended_at,
        occupied_seconds=occupied,
        charged_seconds=calculate_charged_seconds(occupied),
    )
    db.add(log)
    return log


def _parse_report_date(value: Optional[str]) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Use YYYY-MM-DD for report date") from exc


def _day_bounds(value: Optional[str]) -> tuple[datetime, datetime, str]:
    day = _parse_report_date(value).date()
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1), day.isoformat()


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


@router.get("/report")
def get_report(
    date: Optional[str] = None,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    start, end, report_date = _day_bounds(date)
    logs = (
        db.query(models.TableTimeLog)
        .filter(models.TableTimeLog.ended_at >= start, models.TableTimeLog.ended_at < end)
        .order_by(models.TableTimeLog.ended_at.desc(), models.TableTimeLog.id.desc())
        .all()
    )
    summary = {
        "sessions": len(logs),
        "occupied_seconds": sum(int(log.occupied_seconds or 0) for log in logs),
        "charged_seconds": sum(int(log.charged_seconds or 0) for log in logs),
    }

    per_table = {}
    for log in logs:
        row = per_table.setdefault(
            log.table_number,
            {"table_number": log.table_number, "sessions": 0, "occupied_seconds": 0, "charged_seconds": 0},
        )
        row["sessions"] += 1
        row["occupied_seconds"] += int(log.occupied_seconds or 0)
        row["charged_seconds"] += int(log.charged_seconds or 0)

    return {
        "date": report_date,
        "summary": summary,
        "daily_report": [per_table[key] for key in sorted(per_table)],
        "logs": [_serialize_log(log) for log in logs],
    }


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
    now: Optional[datetime] = None,
):
    timer = _get_table(db, table_number)
    if timer.is_running:
        current = now or datetime.utcnow()
        run_seconds = (
            max(0, int((current - timer.started_at).total_seconds()))
            if timer.started_at
            else _current_elapsed_seconds(timer, current)
        )
        timer.elapsed_seconds = _current_elapsed_seconds(timer, current)
        _record_time_log(db, timer, timer.started_at, current, run_seconds)
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
    now: Optional[datetime] = None,
):
    timer = _get_table(db, table_number)
    if timer.is_running:
        current = now or datetime.utcnow()
        run_seconds = (
            max(0, int((current - timer.started_at).total_seconds()))
            if timer.started_at
            else _current_elapsed_seconds(timer, current)
        )
        _record_time_log(db, timer, timer.started_at, current, run_seconds)
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
