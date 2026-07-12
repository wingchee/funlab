import io
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_admin_user, get_membership_user, hash_password, normalize_email, normalize_phone
from database import get_db

router = APIRouter()
_BALANCE_QR_LOGO = Path(__file__).resolve().parents[1] / "assets" / "funlab-logo.jpeg"


def remaining_seconds_for_member(member: models.User) -> int:
    return sum(max(0, int(package.remaining_seconds or 0)) for package in member.packages)


def _member_summary(member: Optional[models.User]) -> Optional[dict]:
    if not member:
        return None
    return {
        "id": member.id,
        "member_code": member.member_code,
        "email": member.email,
        "name": member.name,
        "phone": member.phone,
        "remaining_seconds": remaining_seconds_for_member(member),
        "is_active": bool(member.is_active),
    }


def serialize_member(member: models.User) -> dict:
    payload = _member_summary(member) or {}
    payload.update({
        "notes": member.notes or "",
        "created_at": member.created_at.isoformat() if member.created_at else None,
        "updated_at": member.updated_at.isoformat() if member.updated_at else None,
        "packages_count": len(member.packages),
        "visits_count": len(member.visits),
    })
    return payload


def serialize_package(package: models.MemberPackage) -> dict:
    return {
        "id": package.id,
        "member_id": package.member_id,
        "package_name": package.package_name,
        "total_seconds": int(package.total_seconds or 0),
        "remaining_seconds": int(package.remaining_seconds or 0),
        "notes": package.notes or "",
        "purchased_at": package.purchased_at.isoformat() if package.purchased_at else None,
    }


def serialize_visit(visit: models.MemberVisit) -> dict:
    return {
        "id": visit.id,
        "member_id": visit.member_id,
        "table_time_log_id": visit.table_time_log_id,
        "table_number": visit.table_number,
        "checked_in_at": visit.checked_in_at.isoformat(),
        "checked_out_at": visit.checked_out_at.isoformat(),
        "occupied_seconds": int(visit.occupied_seconds or 0),
        "charged_seconds": int(visit.charged_seconds or 0),
        "package_deducted_seconds": int(visit.package_deducted_seconds or 0),
        "extra_due_seconds": int(visit.extra_due_seconds or 0),
        "notes": visit.notes or "",
    }


def search_members(db: Session, query: str, limit: int = 25) -> list[models.User]:
    term = (query or "").strip()
    if not term:
        return (
            db.query(models.User)
            .filter(models.User.member_code.is_not(None))
            .order_by(models.User.created_at.desc(), models.User.id.desc())
            .limit(limit)
            .all()
        )
    like = f"%{term}%"
    normalized_phone = normalize_phone(term)
    phone_like = f"%{normalized_phone}%" if normalized_phone else like
    return (
        db.query(models.User)
        .filter(
            or_(
                models.User.name.ilike(like),
                models.User.email.ilike(like),
                models.User.phone.ilike(phone_like),
                models.User.member_code.ilike(like),
            ),
        )
        .order_by(models.User.created_at.desc(), models.User.id.desc())
        .limit(limit)
        .all()
    )


def _generate_member_code(db: Session) -> str:
    for _ in range(20):
        code = f"FL{secrets.randbelow(100_000_000):08d}"
        if not db.query(models.User.id).filter(models.User.member_code == code).first():
            return code
    raise HTTPException(status_code=500, detail="Unable to generate unique Member ID")


def _generate_balance_access_token(db: Session) -> str:
    for _ in range(20):
        token = secrets.token_urlsafe(32)
        if not db.query(models.User.id).filter(models.User.balance_access_token == token).first():
            return token
    raise HTTPException(status_code=500, detail="Unable to generate private balance link")


def _member_with_balance_link(db: Session, member_id: int) -> models.User:
    member = (
        db.query(models.User)
        .filter(models.User.id == member_id, models.User.member_code.is_not(None))
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


def _balance_link_response(member: models.User) -> dict:
    return {
        "id": member.id,
        "member_code": member.member_code,
        "balance_access_token": member.balance_access_token,
    }


def _balance_qr_png_bytes(value: str) -> bytes:
    import qrcode  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    logo = Image.open(_BALANCE_QR_LOGO).convert("RGBA")
    logo_limit = max(1, image.width // 5)
    logo.thumbnail((logo_limit, logo_limit), Image.Resampling.LANCZOS)
    plate_size = max(logo.width, logo.height) + max(12, image.width // 50)
    plate = Image.new("RGB", (plate_size, plate_size), "white")
    plate_x = (image.width - plate_size) // 2
    plate_y = (image.height - plate_size) // 2
    image.paste(plate, (plate_x, plate_y))
    logo_x = (image.width - logo.width) // 2
    logo_y = (image.height - logo.height) // 2
    image.paste(logo, (logo_x, logo_y), logo)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@router.post("")
def admin_create_member(
    body: schemas.MemberCreate,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    phone = normalize_phone(body.phone)
    if not name:
        raise HTTPException(status_code=400, detail="Member name is required")
    if not phone:
        raise HTTPException(status_code=400, detail="A valid phone is required")
    if db.query(models.User.id).filter(models.User.phone == phone).first():
        raise HTTPException(status_code=409, detail="Phone is already used by another account")

    balance_access_token = _generate_balance_access_token(db)
    member = models.User(
        email=f"member-{balance_access_token[:24]}@members.funlab.invalid",
        password_hash=hash_password(secrets.token_urlsafe(32)),
        name=name,
        is_admin=False,
        member_code=_generate_member_code(db),
        balance_access_token=balance_access_token,
        phone=phone,
        is_active=True,
        notes="",
    )
    db.add(member)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Member phone or private balance link is already in use") from exc
    db.refresh(member)
    payload = serialize_member(member)
    payload["balance_access_token"] = member.balance_access_token
    return payload


@router.get("/public/{token}")
def public_member_balance(token: str, db: Session = Depends(get_db)):
    member = (
        db.query(models.User)
        .filter(
            models.User.balance_access_token == token,
            models.User.member_code.is_not(None),
            models.User.is_active.is_(True),
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member balance link not found")
    return {
        "name": member.name,
        "member_code": member.member_code,
        "remaining_seconds": remaining_seconds_for_member(member),
        "packages": [
            {
                "package_name": item.package_name,
                "remaining_seconds": int(item.remaining_seconds or 0),
            }
            for item in sorted(member.packages, key=lambda item: item.id)
        ],
    }


@router.post("/{member_id}/balance-link/regenerate")
def regenerate_member_balance_link(
    member_id: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = _member_with_balance_link(db, member_id)
    member.balance_access_token = _generate_balance_access_token(db)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to regenerate private balance link") from exc
    db.refresh(member)
    return _balance_link_response(member)


@router.get("/{member_id}/balance-qr")
def admin_member_balance_qr(
    member_id: int,
    origin: str,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc:
        raise HTTPException(status_code=400, detail="A valid http or https origin is required")
    member = _member_with_balance_link(db, member_id)
    if not member.balance_access_token:
        raise HTTPException(status_code=404, detail="Member balance link not found")
    value = f"{origin.rstrip('/')}/member/{member.balance_access_token}"
    return Response(content=_balance_qr_png_bytes(value), media_type="image/png")


def _membership_removal_conflicts(db: Session, user_id: int) -> list[str]:
    checks = (
        (models.MemberPackage, "packages"),
        (models.MemberVisit, "visits"),
        (models.TableTimer, "active table assignments"),
        (models.TableTimeLog, "time logs"),
    )
    filters = (
        models.MemberPackage.member_id == user_id,
        models.MemberVisit.member_id == user_id,
        models.TableTimer.active_member_id == user_id,
        models.TableTimeLog.member_id == user_id,
    )
    return [
        label
        for (model, label), criterion in zip(checks, filters)
        if db.query(model).filter(criterion).first() is not None
    ]


def add_package_record(
    db: Session,
    member: models.User,
    package_name: str,
    total_seconds: int,
    notes: str = "",
) -> models.MemberPackage:
    total = int(total_seconds or 0)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Package hours must be greater than zero")
    package = models.MemberPackage(
        member_id=member.id,
        package_name=(package_name or "Membership package").strip(),
        total_seconds=total,
        remaining_seconds=total,
        notes=notes.strip(),
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    db.refresh(member)
    return package


def _member_packages_for_update(db: Session, member_id: int):
    return (
        db.query(models.MemberPackage)
        .filter(
            models.MemberPackage.member_id == member_id,
            models.MemberPackage.remaining_seconds > 0,
        )
        .order_by(models.MemberPackage.purchased_at.asc(), models.MemberPackage.id.asc())
        .with_for_update()
    )


def deduct_member_seconds(db: Session, member: models.User, charged_seconds: int) -> dict:
    remaining_charge = max(0, int(charged_seconds or 0))
    deducted = 0
    if remaining_charge == 0:
        return {"deducted_seconds": 0, "extra_due_seconds": 0}

    packages = _member_packages_for_update(db, member.id).all()
    for package in packages:
        if remaining_charge <= 0:
            break
        available = max(0, int(package.remaining_seconds or 0))
        use_seconds = min(available, remaining_charge)
        package.remaining_seconds = available - use_seconds
        remaining_charge -= use_seconds
        deducted += use_seconds

    db.flush()
    return {"deducted_seconds": deducted, "extra_due_seconds": remaining_charge}


def find_member_by_code(db: Session, member_code: str) -> Optional[models.User]:
    code = (member_code or "").strip()
    if not code:
        return None
    return (
        db.query(models.User)
        .filter(
            models.User.member_code.is_not(None),
            models.User.member_code.ilike(code),
            models.User.is_active.is_(True),
        )
        .first()
    )


def resolve_active_member(db: Session, member_code: str) -> models.User:
    member = find_member_by_code(db, member_code)
    if not member:
        raise HTTPException(status_code=404, detail="Active member not found")
    return member


def record_member_visit_for_log(
    db: Session,
    member_id: Optional[int],
    log: Optional[models.TableTimeLog],
    member_started_at: Optional[datetime],
    member_occupied_seconds: int,
    member_charged_seconds: int,
) -> Optional[models.MemberVisit]:
    if not member_id or not log:
        return None

    existing_visit = (
        db.query(models.MemberVisit)
        .filter(models.MemberVisit.table_time_log_id == log.id)
        .first()
    )
    if existing_visit:
        return existing_visit

    member = (
        db.query(models.User)
        .filter(
            models.User.id == member_id,
            models.User.member_code.is_not(None),
            models.User.is_active.is_(True),
        )
        .with_for_update()
        .first()
    )
    if not member:
        return None

    db.flush()
    occupied = max(0, int(member_occupied_seconds or 0))
    charged = max(0, int(member_charged_seconds or 0))
    deduction = deduct_member_seconds(db, member, charged)
    log.member_id = member.id
    log.member_started_at = member_started_at
    visit = models.MemberVisit(
        member_id=member.id,
        table_time_log_id=log.id,
        table_number=log.table_number,
        checked_in_at=member_started_at or log.started_at,
        checked_out_at=log.ended_at,
        occupied_seconds=occupied,
        charged_seconds=charged,
        package_deducted_seconds=deduction["deducted_seconds"],
        extra_due_seconds=deduction["extra_due_seconds"],
    )
    db.add(visit)
    db.flush()
    return visit


def _qr_png_bytes(value: str) -> bytes:
    buffer = io.BytesIO()
    try:
        import qrcode  # noqa: PLC0415

        image = qrcode.make(value)
        image.save(buffer, format="PNG")
    except ModuleNotFoundError:
        from PIL import Image, ImageDraw  # noqa: PLC0415

        image = Image.new("RGB", (320, 320), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 18, 302, 302), outline="black", width=4)
        draw.text((48, 145), value, fill="black")
        image.save(buffer, format="PNG")
    return buffer.getvalue()


def _member_qr_response(member: models.User) -> Response:
    return Response(content=_qr_png_bytes(member.member_code), media_type="image/png")


@router.get("/me")
def member_me(member: models.User = Depends(get_membership_user)):
    return serialize_member(member)


@router.get("/me/packages")
def member_my_packages(member: models.User = Depends(get_membership_user)):
    return [serialize_package(package) for package in sorted(member.packages, key=lambda row: row.id)]


@router.get("/me/visits")
def member_my_visits(member: models.User = Depends(get_membership_user)):
    return [
        serialize_visit(visit)
        for visit in sorted(member.visits, key=lambda row: row.checked_out_at, reverse=True)
    ]


@router.get("/me/qr")
def member_my_qr(member: models.User = Depends(get_membership_user)):
    return _member_qr_response(member)


@router.get("/search")
def admin_search_members(
    q: str = Query("", max_length=120),
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return [serialize_member(member) for member in search_members(db, q)]


@router.get("/{member_id}")
def admin_get_member(
    member_id: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = db.query(models.User).filter(models.User.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    payload = serialize_member(member)
    payload["packages"] = [serialize_package(package) for package in member.packages]
    payload["visits"] = [
        serialize_visit(visit)
        for visit in sorted(member.visits, key=lambda row: row.checked_out_at, reverse=True)
    ]
    return payload


@router.post("/{member_id}/membership")
def admin_promote_membership(
    member_id: int,
    body: schemas.MembershipPromotion,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    account = db.query(models.User).filter(models.User.id == member_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.member_code:
        raise HTTPException(status_code=409, detail="Account already has membership capability")

    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="A valid phone is required")
    if db.query(models.User.id).filter(
        models.User.phone == phone, models.User.id != account.id
    ).first():
        raise HTTPException(status_code=409, detail="Phone is already used by another account")

    member_code = (body.member_code or "").strip().upper()
    if member_code and not re.fullmatch(r"FL\d{8}", member_code):
        raise HTTPException(status_code=400, detail="Member ID must use FL followed by 8 digits")
    if not member_code:
        member_code = _generate_member_code(db)
    elif db.query(models.User.id).filter(
        models.User.member_code.ilike(member_code), models.User.id != account.id
    ).first():
        raise HTTPException(status_code=409, detail="Member ID is already used by another account")

    account.phone = phone
    account.member_code = member_code
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phone or Member ID is already in use") from exc
    db.refresh(account)
    return serialize_member(account)


@router.delete("/{member_id}/membership")
def admin_remove_membership(
    member_id: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    account = db.query(models.User).filter(models.User.id == member_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.member_code:
        raise HTTPException(status_code=409, detail="Account has no membership capability")

    conflicts = _membership_removal_conflicts(db, account.id)
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail="Membership cannot be removed while retained references exist: "
            + ", ".join(conflicts),
        )
    account.member_code = None
    account.phone = None
    db.commit()
    db.refresh(account)
    return {
        "id": account.id,
        "email": account.email,
        "name": account.name,
        "is_admin": bool(account.is_admin),
        "member_code": account.member_code,
        "phone": account.phone,
        "is_active": bool(account.is_active),
    }


@router.put("/{member_id}")
def admin_update_member(
    member_id: int,
    body: schemas.MemberUpdate,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = db.query(models.User).filter(
        models.User.id == member_id,
        models.User.member_code.is_not(None),
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if body.name.strip():
        member.name = body.name.strip()
    if body.email.strip():
        member.email = normalize_email(body.email)
    if body.phone.strip():
        normalized_phone = normalize_phone(body.phone)
        if not normalized_phone:
            raise HTTPException(status_code=400, detail="Member phone is required")
        member.phone = normalized_phone
    if body.password:
        member.password_hash = hash_password(body.password)
    if body.is_active is not None:
        member.is_active = bool(body.is_active)
    member.notes = body.notes.strip()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A member already exists for this email or phone",
        ) from exc
    db.refresh(member)
    return serialize_member(member)


@router.get("/{member_id}/packages")
def admin_member_packages(
    member_id: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = db.query(models.User).filter(
        models.User.id == member_id,
        models.User.member_code.is_not(None),
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return [serialize_package(package) for package in sorted(member.packages, key=lambda row: row.id)]


@router.post("/{member_id}/packages")
def admin_add_member_package(
    member_id: int,
    body: schemas.MemberPackageCreate,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = db.query(models.User).filter(
        models.User.id == member_id,
        models.User.member_code.is_not(None),
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    package = add_package_record(db, member, body.package_name, body.total_seconds, body.notes)
    return serialize_package(package)


@router.put("/{member_id}/packages/{package_id}")
def admin_update_member_package(
    member_id: int,
    package_id: int,
    body: schemas.MemberPackageUpdate,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    package = (
        db.query(models.MemberPackage)
        .filter(models.MemberPackage.member_id == member_id, models.MemberPackage.id == package_id)
        .first()
    )
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    if body.package_name.strip():
        package.package_name = body.package_name.strip()
    if body.total_seconds is not None:
        package.total_seconds = max(0, int(body.total_seconds))
    if body.remaining_seconds is not None:
        package.remaining_seconds = max(0, int(body.remaining_seconds))
    package.notes = body.notes.strip()
    db.commit()
    db.refresh(package)
    return serialize_package(package)


@router.get("/{member_id}/visits")
def admin_member_visits(
    member_id: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = db.query(models.User).filter(
        models.User.id == member_id,
        models.User.member_code.is_not(None),
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return [
        serialize_visit(visit)
        for visit in sorted(member.visits, key=lambda row: row.checked_out_at, reverse=True)
    ]


@router.get("/{member_id}/qr")
def admin_member_qr(
    member_id: int,
    _: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    member = db.query(models.User).filter(
        models.User.id == member_id,
        models.User.member_code.is_not(None),
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return _member_qr_response(member)
