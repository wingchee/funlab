from datetime import datetime, time, timedelta
import secrets
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_admin_user
from database import get_db
from routers import memberships

router = APIRouter()
TABLE_COUNT = 14
FIRST_HOUR_SECONDS = 60 * 60
HALF_HOUR_SECONDS = 30 * 60
GRACE_SECONDS = 10 * 60
SETTLEMENT_RETRIES = 3


def _new_run_token() -> str:
    return secrets.token_urlsafe(18)


def _timer_state_query(db: Session, timer: models.TableTimer):
    query = db.query(models.TableTimer).filter(
        models.TableTimer.id == timer.id,
        models.TableTimer.state_version == int(timer.state_version or 0),
    )
    if timer.run_token is None:
        return query.filter(models.TableTimer.run_token.is_(None))
    return query.filter(models.TableTimer.run_token == timer.run_token)


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
    active_member = getattr(timer, "active_member", None)
    return {
        "id": timer.id,
        "table_number": timer.table_number,
        "status": "Occupied" if timer.is_running else "Free",
        "is_running": bool(timer.is_running),
        "elapsed_seconds": elapsed,
        "started_at": timer.started_at.isoformat() if timer.started_at else None,
        "updated_at": timer.updated_at.isoformat() if timer.updated_at else None,
        "charged_seconds": calculate_charged_seconds(elapsed),
        "active_member": memberships._member_summary(active_member),
        "active_member_started_at": (
            timer.active_member_started_at.isoformat()
            if timer.active_member_started_at
            else None
        ),
    }


def _serialize_log(log: models.TableTimeLog) -> dict:
    visit = getattr(log, "member_visit", None)
    return {
        "id": log.id,
        "table_number": log.table_number,
        "member_id": log.member_id,
        "member": memberships._member_summary(getattr(log, "member", None)),
        "started_at": log.started_at.isoformat(),
        "ended_at": log.ended_at.isoformat(),
        "occupied_seconds": int(log.occupied_seconds or 0),
        "charged_seconds": int(log.charged_seconds or 0),
        "package_deducted_seconds": int(visit.package_deducted_seconds or 0) if visit else 0,
        "extra_due_seconds": int(visit.extra_due_seconds or 0) if visit else 0,
    }


def _record_time_log(
    db: Session,
    timer: models.TableTimer,
    started_at: Optional[datetime],
    ended_at: datetime,
    occupied_seconds: int,
    member_id: Optional[int] = None,
    member_started_at: Optional[datetime] = None,
) -> Optional[models.TableTimeLog]:
    occupied = max(0, int(occupied_seconds or 0))
    if occupied <= 0:
        return None
    log = models.TableTimeLog(
        table_number=timer.table_number,
        member_id=member_id,
        member_started_at=member_started_at,
        started_at=started_at or ended_at - timedelta(seconds=occupied),
        ended_at=ended_at,
        occupied_seconds=occupied,
        charged_seconds=calculate_charged_seconds(occupied),
    )
    db.add(log)
    db.flush()
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


def _insert_missing_table_timers(db: Session, missing: list[int]) -> None:
    rows = [
        {
            "table_number": number,
            "is_running": False,
            "elapsed_seconds": 0,
            "state_version": 0,
        }
        for number in missing
    ]
    dialect_name = db.get_bind().dialect.name
    try:
        if dialect_name == "sqlite":
            statement = sqlite_insert(models.TableTimer).values(rows)
            db.execute(statement.on_conflict_do_nothing(index_elements=["table_number"]))
        elif dialect_name == "postgresql":
            statement = postgresql_insert(models.TableTimer).values(rows)
            db.execute(statement.on_conflict_do_nothing(index_elements=["table_number"]))
        else:
            for row in rows:
                db.add(models.TableTimer(**row))
        db.commit()
    except IntegrityError:
        db.rollback()
        remaining = {
            row.table_number
            for row in db.query(models.TableTimer.table_number).all()
        }
        if any(number not in remaining for number in range(1, TABLE_COUNT + 1)):
            raise


def _ensure_table_timers(db: Session) -> None:
    existing = {
        row.table_number
        for row in db.query(models.TableTimer.table_number).all()
    }
    missing = [number for number in range(1, TABLE_COUNT + 1) if number not in existing]
    if missing:
        _insert_missing_table_timers(db, missing)


def _get_table(db: Session, table_number: int) -> models.TableTimer:
    _ensure_table_timers(db)
    if table_number < 1 or table_number > TABLE_COUNT:
        raise HTTPException(status_code=404, detail="Table not found")
    timer = db.query(models.TableTimer).filter(models.TableTimer.table_number == table_number).first()
    if not timer:
        raise HTTPException(status_code=404, detail="Table not found")
    return timer


def _all_timers_for_update(db: Session):
    """Lock the full reset set before member/package locks can be acquired."""
    return (
        db.query(models.TableTimer)
        .order_by(models.TableTimer.table_number.asc())
        .with_for_update()
    )


def _settle_running_timer(
    timer: models.TableTimer,
    db: Session,
    current: datetime,
    reset_elapsed: bool,
) -> Optional[models.TableTimeLog]:
    original_run_token = timer.run_token
    candidate = timer
    for _ in range(SETTLEMENT_RETRIES):
        if not candidate.is_running:
            return None

        run_seconds = (
            max(0, int((current - candidate.started_at).total_seconds()))
            if candidate.started_at
            else _current_elapsed_seconds(candidate, current)
        )
        total_elapsed = _current_elapsed_seconds(candidate, current)
        member_id = candidate.active_member_id
        member_started_at = candidate.active_member_started_at
        if member_id and not member_started_at:
            member_started_at = candidate.started_at or current - timedelta(seconds=run_seconds)
        if member_started_at:
            member_started_at = min(member_started_at, current)

        claimed = (
            _timer_state_query(db, candidate)
            .filter(models.TableTimer.is_running.is_(True))
            .update(
                {
                    models.TableTimer.is_running: False,
                    models.TableTimer.started_at: None,
                    models.TableTimer.run_token: None,
                    models.TableTimer.state_version: int(candidate.state_version or 0) + 1,
                    models.TableTimer.elapsed_seconds: 0 if reset_elapsed else total_elapsed,
                    models.TableTimer.active_member_id: None,
                    models.TableTimer.active_member_started_at: None,
                },
                synchronize_session=False,
            )
        )
        if claimed == 1:
            log = _record_time_log(
                db,
                candidate,
                candidate.started_at,
                current,
                run_seconds,
                member_id=member_id,
                member_started_at=member_started_at,
            )
            if log and member_id:
                member_occupied_seconds = max(
                    0,
                    int((current - (member_started_at or log.started_at)).total_seconds()),
                )
                memberships.record_member_visit_for_log(
                    db,
                    member_id,
                    log,
                    member_started_at,
                    member_occupied_seconds,
                    calculate_charged_seconds(member_occupied_seconds),
                )
            return log

        candidate = (
            db.query(models.TableTimer)
            .populate_existing()
            .filter(models.TableTimer.id == timer.id)
            .first()
        )
        if not candidate or not candidate.is_running:
            return None
        if candidate.run_token != original_run_token:
            return None

    raise HTTPException(status_code=409, detail="Table changed during settlement; try again")


def _reset_timer(timer: models.TableTimer, db: Session, current: datetime) -> None:
    if timer.is_running:
        _settle_running_timer(timer, db, current, reset_elapsed=True)
        return
    cleared = (
        _timer_state_query(db, timer)
        .filter(models.TableTimer.is_running.is_(False))
        .update(
            {
                models.TableTimer.active_member_id: None,
                models.TableTimer.active_member_started_at: None,
                models.TableTimer.elapsed_seconds: 0,
                models.TableTimer.started_at: None,
                models.TableTimer.run_token: None,
                models.TableTimer.state_version: int(timer.state_version or 0) + 1,
            },
            synchronize_session=False,
        )
    )
    if cleared != 1:
        raise HTTPException(status_code=409, detail="Table changed during reset; try again")


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


@router.post("/reset-all")
def reset_all_tables(
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
    now: Optional[datetime] = None,
):
    _ensure_table_timers(db)
    current = now or datetime.utcnow()
    rows = _all_timers_for_update(db).all()
    for timer in rows:
        _reset_timer(timer, db, current)
    db.commit()
    return [_serialize(row, now=current) for row in rows]


@router.get("/{table_number}")
def get_table(table_number: int, db: Session = Depends(get_db)):
    return _serialize(_get_table(db, table_number), now=datetime.utcnow())


@router.post("/{table_number}/start")
def start_table(
    table_number: int,
    body: Optional[schemas.TableTimerStartRequest] = Body(None),
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    timer = _get_table(db, table_number)
    if not timer.is_running:
        current = datetime.utcnow()
        member_id = timer.active_member_id
        if body and body.member_code:
            member = memberships.resolve_active_member(db, body.member_code)
            member_id = member.id
        started = (
            _timer_state_query(db, timer)
            .filter(models.TableTimer.is_running.is_(False))
            .update(
                {
                    models.TableTimer.active_member_id: member_id,
                    models.TableTimer.active_member_started_at: current if member_id else None,
                    models.TableTimer.is_running: True,
                    models.TableTimer.started_at: current,
                    models.TableTimer.run_token: _new_run_token(),
                    models.TableTimer.state_version: int(timer.state_version or 0) + 1,
                },
                synchronize_session=False,
            )
        )
        if started != 1:
            db.rollback()
            timer = (
                db.query(models.TableTimer)
                .populate_existing()
                .filter(models.TableTimer.id == timer.id)
                .one()
            )
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
        _settle_running_timer(timer, db, current, reset_elapsed=False)
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
    current = now or datetime.utcnow()
    _reset_timer(timer, db, current)
    db.commit()
    db.refresh(timer)
    return _serialize(timer, now=current)


@router.put("/{table_number}")
def set_table(
    table_number: int,
    body: schemas.TableTimerSetRequest,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
    now: Optional[datetime] = None,
):
    if body.elapsed_seconds < 0:
        raise HTTPException(status_code=400, detail="Elapsed seconds must be 0 or greater")
    timer = _get_table(db, table_number)
    current = now or datetime.utcnow()
    if timer.is_running and not body.is_running:
        _settle_running_timer(timer, db, current, reset_elapsed=False)
        db.flush()
        db.expire(timer)
        db.refresh(timer)
        if timer.is_running:
            db.rollback()
            raise HTTPException(status_code=409, detail="A newer table run has started; try again")

    was_running = bool(timer.is_running)
    member_started_at = timer.active_member_started_at
    if body.is_running and timer.active_member_id and not member_started_at:
        member_started_at = current
    run_token = timer.run_token if was_running else (_new_run_token() if body.is_running else None)
    updated = (
        _timer_state_query(db, timer)
        .filter(models.TableTimer.is_running.is_(was_running))
        .update(
            {
                models.TableTimer.elapsed_seconds: int(body.elapsed_seconds),
                models.TableTimer.is_running: bool(body.is_running),
                models.TableTimer.started_at: current if body.is_running else None,
                models.TableTimer.run_token: run_token if body.is_running else None,
                models.TableTimer.active_member_started_at: member_started_at,
                models.TableTimer.state_version: int(timer.state_version or 0) + 1,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Table changed while it was being set; try again")
    db.commit()
    db.refresh(timer)
    return _serialize(timer, now=datetime.utcnow())


@router.post("/{table_number}/member")
def attach_member_to_table(
    table_number: int,
    body: schemas.TableMemberAttachRequest,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
    now: Optional[datetime] = None,
):
    timer = _get_table(db, table_number)
    requested_code = body.member_code.strip()
    if timer.is_running and timer.active_member_id:
        if requested_code:
            member = memberships.resolve_active_member(db, requested_code)
            if member.id == timer.active_member_id:
                return _serialize(timer, now=now or datetime.utcnow())
        raise HTTPException(
            status_code=409,
            detail="Stop the running table before changing or removing its member",
        )

    member = memberships.resolve_active_member(db, requested_code) if requested_code else None
    if timer.is_running and not member:
        return _serialize(timer, now=now or datetime.utcnow())
    attached = _timer_state_query(db, timer).filter(
        models.TableTimer.is_running.is_(bool(timer.is_running))
    )
    if timer.is_running:
        attached = attached.filter(models.TableTimer.active_member_id.is_(None))
    attached = attached.update(
        {
            models.TableTimer.active_member_id: member.id if member else None,
            models.TableTimer.active_member_started_at: (
                (now or datetime.utcnow()) if timer.is_running and member else None
            ),
            models.TableTimer.state_version: int(timer.state_version or 0) + 1,
        },
        synchronize_session=False,
    )
    if attached != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Table state changed; scan the member again")
    db.commit()
    db.refresh(timer)
    return _serialize(timer, now=datetime.utcnow())
