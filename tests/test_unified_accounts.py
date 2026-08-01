import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import models  # noqa: E402
import schemas  # noqa: E402
from auth import (  # noqa: E402
    create_token,
    get_admin_user,
    get_current_user,
    get_membership_user,
    hash_password,
    verify_password,
)
from routers import favorites  # noqa: E402
from routers import auth as auth_router  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _member(db, **overrides):
    values = {
        "email": "member@example.com",
        "password_hash": hash_password("member-pass"),
        "name": "Member",
        "is_admin": False,
        "member_code": "FL00000001",
        "phone": "60123456789",
        "is_active": True,
        "notes": "",
    }
    values.update(overrides)
    user = models.User(**values)
    db.add(user)
    db.commit()
    return user


def test_existing_admin_logs_in_with_email_and_has_no_membership(db):
    admin = models.User(
        email="admin@example.com",
        password_hash=hash_password("admin-pass"),
        name="Admin",
        is_admin=True,
    )
    db.add(admin)
    db.commit()

    result = auth_router.login(
        schemas.AccountLogin(identifier="ADMIN@example.com", password="admin-pass"), db=db
    )

    assert result["user"]["is_admin"] is True
    assert result["user"]["member_code"] is None


def test_preserved_space_padded_mixed_case_email_logs_in_normalized(db):
    admin = models.User(
        email=" Admin@Example.COM ",
        password_hash=hash_password("admin-pass"),
        name="Admin",
        is_admin=True,
    )
    db.add(admin)
    db.commit()

    result = auth_router.login(
        schemas.AccountLogin(identifier="admin@example.com", password="admin-pass"),
        db=db,
    )

    assert result["user"]["id"] == admin.id
    assert admin.email == " Admin@Example.COM "


def test_public_registration_route_returns_not_found():
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")

    assert TestClient(app).post("/api/auth/register", json={}).status_code == 404


@pytest.mark.parametrize("identifier", ["member@example.com", "60123456789", "fl00000001"])
def test_login_accepts_email_phone_or_member_id(db, identifier):
    _member(db)
    result = auth_router.login(
        schemas.AccountLogin(identifier=identifier, password="member-pass"), db=db
    )
    assert result["user"]["member_code"] == "FL00000001"


def test_inactive_and_wrong_password_share_generic_error(db):
    _member(db)
    _member(
        db,
        email="inactive@example.com",
        phone="60111111111",
        member_code="FL00000002",
        is_active=False,
    )

    for body in (
        schemas.AccountLogin(identifier="inactive@example.com", password="member-pass"),
        schemas.AccountLogin(identifier="member@example.com", password="wrong-pass"),
    ):
        with pytest.raises(HTTPException) as error:
            auth_router.login(body, db=db)
        assert error.value.status_code == 401
        assert error.value.detail == "Invalid credentials"


def test_membership_and_admin_dependencies_accept_unified_roles(db):
    admin_only = models.User(
        email="admin@example.com",
        password_hash=hash_password("admin-pass"),
        name="Admin",
        is_admin=True,
    )
    db.add(admin_only)
    db.commit()
    with pytest.raises(HTTPException) as error:
        get_membership_user(admin_only)
    assert error.value.status_code == 403

    membership_admin = _member(
        db,
        email="owner@example.com",
        phone="60122222222",
        member_code="FL00000003",
        is_admin=True,
    )
    assert get_membership_user(membership_admin) is membership_admin
    assert get_admin_user(membership_admin) is membership_admin


def test_real_token_is_rejected_everywhere_after_account_deactivation(db):
    user = _member(db, is_admin=True)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=create_token(user.id)
    )
    user.is_active = False
    db.commit()

    authenticated_entry_points = (
        lambda: auth_router.me(get_current_user(credentials, db)),
        lambda: favorites.list_favorite_ids(get_current_user(credentials, db), db),
        lambda: get_admin_user(get_current_user(credentials, db)),
    )
    for invoke in authenticated_entry_points:
        with pytest.raises(HTTPException) as error:
            invoke()
        assert error.value.status_code == 401
        assert error.value.detail == "Invalid or expired token"


def _account(db, *, email, password, phone=None, member_code=None):
    account = models.User(
        email=email,
        password_hash=hash_password(password),
        name=email,
        is_admin=False,
        phone=phone,
        member_code=member_code,
        is_active=True,
        notes="",
    )
    db.add(account)
    db.commit()
    return account


def test_login_email_namespace_wins_over_phone_and_member_id(db):
    identifier = "60128889999"
    _account(db, email="phone@example.com", password="phone-pass", phone=identifier)
    _account(db, email="code@example.com", password="code-pass", member_code=identifier)
    email_owner = _account(db, email=identifier, password="email-pass")

    result = auth_router.login(
        schemas.AccountLogin(identifier=identifier, password="email-pass"), db=db
    )

    assert result["user"]["id"] == email_owner.id


def test_login_phone_namespace_wins_over_member_id(db):
    identifier = "60127778888"
    _account(db, email="code@example.com", password="code-pass", member_code=identifier)
    phone_owner = _account(
        db, email="phone@example.com", password="phone-pass", phone=identifier
    )

    result = auth_router.login(
        schemas.AccountLogin(identifier=identifier, password="phone-pass"), db=db
    )

    assert result["user"]["id"] == phone_owner.id


def test_profile_update_changes_and_normalizes_the_current_users_email(db):
    account = _account(db, email="before@example.com", password="current-pass")

    result = auth_router.update_profile(
        schemas.ProfileUpdate(
            current_password="current-pass", email="  AFTER@Example.COM  "
        ),
        current_user=account,
        db=db,
    )

    assert result["email"] == "after@example.com"
    assert db.get(models.User, account.id).email == "after@example.com"
    assert "password" not in result
    assert "password_hash" not in result


def test_profile_update_changes_password_and_invalidates_the_old_password(db):
    account = _account(db, email="account@example.com", password="current-pass")

    result = auth_router.update_profile(
        schemas.ProfileUpdate(current_password="current-pass", new_password="new-password"),
        current_user=account,
        db=db,
    )

    assert verify_password("new-password", account.password_hash)
    assert not verify_password("current-pass", account.password_hash)
    with pytest.raises(HTTPException) as error:
        auth_router.login(
            schemas.AccountLogin(identifier="account@example.com", password="current-pass"), db=db
        )
    assert error.value.status_code == 401
    assert auth_router.login(
        schemas.AccountLogin(identifier="account@example.com", password="new-password"), db=db
    )["user"]["id"] == account.id
    assert "password" not in result
    assert "password_hash" not in result


def test_profile_update_rejects_wrong_current_password(db):
    account = _account(db, email="account@example.com", password="current-pass")

    with pytest.raises(HTTPException) as error:
        auth_router.update_profile(
            schemas.ProfileUpdate(current_password="wrong-password", email="new@example.com"),
            current_user=account,
            db=db,
        )

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid current password"


@pytest.mark.parametrize(
    "email,new_password",
    [("", ""), ("new@example.com", "new-password")],
)
def test_profile_update_requires_exactly_one_change(db, email, new_password):
    account = _account(db, email="account@example.com", password="current-pass")

    with pytest.raises(HTTPException) as error:
        auth_router.update_profile(
            schemas.ProfileUpdate(
                current_password="current-pass", email=email, new_password=new_password
            ),
            current_user=account,
            db=db,
        )

    assert error.value.status_code == 400


@pytest.mark.parametrize("email", ["", "   ", "not-an-email", "missing-domain@"])
def test_profile_update_rejects_blank_or_malformed_email(db, email):
    account = _account(db, email="account@example.com", password="current-pass")

    with pytest.raises(HTTPException) as error:
        auth_router.update_profile(
            schemas.ProfileUpdate(current_password="current-pass", email=email),
            current_user=account,
            db=db,
        )

    assert error.value.status_code == 400


def test_profile_update_rejects_an_email_already_in_use(db, mocker):
    account = _account(db, email="account@example.com", password="current-pass")
    _account(db, email="taken@example.com", password="other-pass")
    rollback = mocker.spy(db, "rollback")

    with pytest.raises(HTTPException) as error:
        auth_router.update_profile(
            schemas.ProfileUpdate(current_password="current-pass", email="TAKEN@example.com"),
            current_user=account,
            db=db,
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Email is already in use"
    rollback.assert_called_once()
    assert db.get(models.User, account.id).email == "account@example.com"


def test_profile_update_rejects_a_short_new_password(db):
    account = _account(db, email="account@example.com", password="current-pass")

    with pytest.raises(HTTPException) as error:
        auth_router.update_profile(
            schemas.ProfileUpdate(current_password="current-pass", new_password="short"),
            current_user=account,
            db=db,
        )

    assert error.value.status_code == 400


@pytest.mark.parametrize("new_password", ["a" * 73, "😀" * 19])
def test_profile_update_rejects_new_passwords_over_bcrypts_byte_limit(db, new_password):
    account = _account(db, email="account@example.com", password="current-pass")
    password_hash_before_update = account.password_hash

    with pytest.raises(HTTPException) as error:
        auth_router.update_profile(
            schemas.ProfileUpdate(current_password="current-pass", new_password=new_password),
            current_user=account,
            db=db,
        )

    assert error.value.status_code == 400
    assert "72 bytes" in error.value.detail
    assert db.get(models.User, account.id).password_hash == password_hash_before_update
    assert verify_password("current-pass", account.password_hash)


def test_profile_update_http_route_requires_authentication():
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")

    response = TestClient(app).put(
        "/api/auth/profile",
        json={"current_password": "current-pass", "email": "new@example.com"},
    )

    assert response.status_code == 401
