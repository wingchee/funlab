# Unified Account Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate `users` and `members` identities with one `users` table, one bcrypt password, one JWT, and one browser session while preserving existing production administrators.

**Architecture:** Extend `users` with optional membership attributes and make all membership foreign keys target `users.id`. Keep the `/api/members` resource routes for membership data, but move registration and login into the canonical auth router and remove the second password/token implementation. Use a schema-inspecting Alembic revision that preserves production `users` and user favorites while discarding the user-approved experimental local member data.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, SQLite, bcrypt, python-jose JWT, React 18 via Babel, Docker Compose, pytest.

## Global Constraints

- `users` is the only account table after migration; there is no `members` table or `Member` ORM model.
- Existing production user IDs, email addresses, bcrypt password hashes, names, `is_admin` values, creation timestamps, and user-owned favorites remain unchanged.
- `member_code` and `phone` are nullable for administrator-only accounts and unique when populated.
- A user is membership-capable only when `member_code` is populated.
- Existing local member, member-package, member-visit, member-favorite, and active-member timer data may be discarded.
- All accounts use bcrypt and the existing JWT format; the PBKDF2 member password and HMAC member-token implementations are removed.
- Login accepts normalized email, normalized phone, or case-insensitive Member ID and returns a generic error for all invalid credentials.
- The frontend stores one token and one account object; `pc_member_token` and `pc_token_type` are removed.
- Production deployment must create and verify a SQLite backup outside the Docker volume before running migrations.
- Rotating the production `SECRET_KEY` during this deployment intentionally signs everyone out once.

---

## File Structure

- `backend/models.py`: owns the unified `User` ORM model and all relationships to membership data.
- `backend/auth.py`: owns bcrypt, unified JWT creation/decoding, and current-user/admin/member dependencies.
- `backend/schemas.py`: owns unified login, registration, and membership-edit request contracts.
- `backend/routers/auth.py`: owns canonical registration, login, and current-account endpoints.
- `backend/routers/memberships.py`: owns membership profile, QR, package, visit, search, and staff-management behavior for membership-capable `User` rows.
- `backend/routers/favorites.py`: owns the single `Favorite.user_id` path.
- `backend/alembic/versions/20260711_0003_unified_account_table.py`: converts production-style and experimental local schemas to the unified schema.
- `frontend/index.html`: owns the single browser session and unified sign-in/registration UI.
- `scripts/deploy_lightsail_ubuntu.sh`: creates and verifies the production backup before container replacement.
- `DEPLOYMENT.md` and `DIGITALOCEAN_UBUNTU_DEPLOYMENT.md`: document backup, migration, rollback, and unified login operations.
- `tests/test_unified_accounts.py`: focused unified identity and auth behavior.
- Existing membership, favorites, migration, timetable, frontend, and deployment tests: regression coverage updated to the new model.

---

### Task 1: Convert The Schema To One Account Table

**Files:**
- Modify: `backend/models.py:6-116`
- Create: `backend/alembic/versions/20260711_0003_unified_account_table.py`
- Modify: `tests/test_migrations.py:22-337`

**Interfaces:**
- Produces: `models.User` with `member_code`, `phone`, `is_active`, `notes`, `updated_at`, `packages`, and `visits`.
- Produces: `member_packages.member_id`, `member_visits.member_id`, `table_timers.active_member_id`, and `table_time_logs.member_id` foreign keys targeting `users.id`.
- Produces: Alembic head revision `20260711_0003`.
- Removes: `models.Member`, `Favorite.member_id`, and the `members` table.

- [ ] **Step 1: Replace migration expectations with unified-schema tests**

Update the fresh-schema assertion and add a production-style preservation test with these exact checks:

```python
def _columns(connection, table):
    return {row[1]: row for row in connection.execute(f"PRAGMA table_info('{table}')")}

def _foreign_keys(connection, table):
    return connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()

def test_upgrade_creates_unified_account_schema(self):
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "fresh.db"
        result = self._upgrade(database_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("users", tables)
            self.assertNotIn("members", tables)
            self.assertTrue({"member_packages", "member_visits"}.issubset(tables))
            user_columns = _columns(connection, "users")
            for name in ("member_code", "phone", "is_active", "notes", "updated_at"):
                self.assertIn(name, user_columns)
            self.assertEqual(user_columns["member_code"][3], 0)
            self.assertEqual(user_columns["phone"][3], 0)
            for table, column in (
                ("member_packages", "member_id"),
                ("member_visits", "member_id"),
                ("table_timers", "active_member_id"),
                ("table_time_logs", "member_id"),
            ):
                self.assertTrue(any(
                    row[2] == "users" and row[3] == column
                    for row in _foreign_keys(connection, table)
                ))
            self.assertNotIn("member_id", _columns(connection, "favorites"))
            self.assertEqual(
                connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                "20260711_0003",
            )
```

Create a production-style database containing `users`, `patterns`, and `favorites`, insert an administrator with a known bcrypt string, upgrade it, and assert the row is byte-for-byte preserved:

```python
expected = (7, "admin@example.com", "$2b$12$preserved-hash", "Admin", 1)
actual = connection.execute(
    "SELECT id, email, password_hash, name, is_admin FROM users WHERE id=7"
).fetchone()
self.assertEqual(actual, expected)
self.assertEqual(
    connection.execute(
        "SELECT user_id, pattern_id FROM favorites WHERE id=9"
    ).fetchone(),
    (7, 3),
)
```

Replace the legacy-member preservation test with a disposable-local-schema test that creates all experimental member tables, inserts member-linked rows, upgrades, and asserts the member-linked rows are gone while the `users` row remains.

- [ ] **Step 2: Run migration tests to verify RED**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: FAIL because `members` still exists, membership foreign keys target `members`, and Alembic head is `20260711_0002`.

- [ ] **Step 3: Change the ORM to the unified model**

Replace `User` and remove `Member` with this model shape:

```python
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    member_code = Column(String, unique=True, nullable=True, index=True)
    phone = Column(String, unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    packages = relationship("MemberPackage", back_populates="member", cascade="all, delete-orphan")
    visits = relationship("MemberVisit", back_populates="member", cascade="all, delete-orphan")
```

Change `MemberPackage.member`, `MemberVisit.member`, `TableTimer.active_member`, and `TableTimeLog.member` to `relationship("User")`; change all four foreign-key targets from `members.id` to `users.id`. Reduce `Favorite` to:

```python
class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        Index("uq_favorites_user_pattern", "user_id", "pattern_id", unique=True),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pattern_id = Column(Integer, ForeignKey("patterns.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="favorites")
    pattern = relationship("Pattern", back_populates="favorites")
```

- [ ] **Step 4: Implement the schema-inspecting Alembic revision**

Create revision `20260711_0003` with `down_revision = "20260711_0002"`. Implement helpers `_tables()`, `_columns(table)`, `_indexes(table)`, and `_drop_if_present(table)` using `sa.inspect(op.get_bind())`.

The upgrade must perform these operations in order:

```python
def upgrade() -> None:
    connection = op.get_bind()
    user_columns = _columns("users")
    with op.batch_alter_table("users") as batch:
        if "member_code" not in user_columns:
            batch.add_column(sa.Column("member_code", sa.String(), nullable=True))
        if "phone" not in user_columns:
            batch.add_column(sa.Column("phone", sa.String(), nullable=True))
        if "is_active" not in user_columns:
            batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        if "notes" not in user_columns:
            batch.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))
        if "updated_at" not in user_columns:
            batch.add_column(sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))

    duplicates = connection.execute(sa.text(
        "SELECT LOWER(TRIM(email)) normalized_email FROM users "
        "GROUP BY LOWER(TRIM(email)) HAVING COUNT(*) > 1"
    )).scalars().all()
    if duplicates:
        raise RuntimeError("Duplicate normalized user emails: " + ", ".join(duplicates))
    null_admin_ids = connection.execute(sa.text(
        "SELECT id FROM users WHERE is_admin IS NULL ORDER BY id"
    )).scalars().all()
    if null_admin_ids:
        raise RuntimeError(
            "NULL is_admin values for user IDs: "
            + ", ".join(str(user_id) for user_id in null_admin_ids)
        )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("is_admin", existing_type=sa.Boolean(), nullable=False)

    for table in ("member_visits", "member_packages"):
        _drop_if_present(table)

    # Batch-recreate timers/logs so their member columns target users.
    # Preserve non-member timer/log columns but set member references to NULL.
    connection.execute(sa.text("UPDATE table_timers SET active_member_id=NULL, active_member_started_at=NULL"))
    connection.execute(sa.text("UPDATE table_time_logs SET member_id=NULL, member_started_at=NULL"))
    _rebuild_timers_and_logs_with_user_fks()

    if "member_id" in _columns("favorites"):
        connection.execute(sa.text("DELETE FROM favorites WHERE user_id IS NULL"))
        with op.batch_alter_table("favorites") as batch:
            batch.drop_column("member_id")
    if "user_id" in _columns("favorites"):
        with op.batch_alter_table("favorites") as batch:
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
    _replace_favorite_indexes()

    _drop_if_present("members")
    _create_member_packages_referencing_users()
    _create_member_visits_referencing_users()
    _create_unique_user_membership_indexes()
```

Implement `_rebuild_timers_and_logs_with_user_fks()` with `op.batch_alter_table(..., recreate="always")`, dropping any existing member foreign key and creating `fk_table_timers_active_member_id_users` / `fk_table_time_logs_member_id_users`. Implement the package and visit tables with the same columns and indexes as revision `0001`, except their foreign keys target `users.id`.

Make `downgrade()` raise:

```python
raise RuntimeError(
    "Unified account migration cannot be downgraded; restore the pre-migration SQLite backup"
)
```

- [ ] **Step 5: Run migration tests to verify GREEN**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: all migration tests PASS, the fresh database has no `members` table, and the production-style administrator row is preserved.

- [ ] **Step 6: Commit the schema unit**

```bash
git add backend/models.py backend/alembic/versions/20260711_0003_unified_account_table.py tests/test_migrations.py
git commit -m "feat: consolidate accounts into users table"
```

---

### Task 2: Implement One Password, Token, Registration, And Login

**Files:**
- Modify: `backend/auth.py:1-66`
- Modify: `backend/schemas.py:1-67`
- Modify: `backend/routers/auth.py:1-35`
- Delete: `backend/member_auth.py`
- Create: `tests/test_unified_accounts.py`

**Interfaces:**
- Produces: `normalize_email(value: str) -> str`, `normalize_phone(value: str) -> str`, `serialize_account(user: User) -> dict`.
- Produces: `get_membership_user(...) -> User`, which requires `member_code`, `is_active`, and a valid unified JWT.
- Produces: `POST /api/auth/register` and `POST /api/auth/login`, both returning `{access_token, token_type, user}`.
- Consumes: membership fields created by Task 1.
- Removes: every import and function in `member_auth.py`.

- [ ] **Step 1: Write focused failing unified-auth tests**

Create `tests/test_unified_accounts.py` with an in-memory SQLite database and dependency overrides. Cover these exact behaviors:

```python
def test_existing_admin_logs_in_with_email_and_has_no_membership(self):
    admin = models.User(
        email="admin@example.com", password_hash=hash_password("admin-pass"),
        name="Admin", is_admin=True,
    )
    db.add(admin); db.commit()
    result = auth_router.login(
        schemas.AccountLogin(identifier="ADMIN@example.com", password="admin-pass"), db=db
    )
    assert result["user"]["is_admin"] is True
    assert result["user"]["member_code"] is None

def test_member_registration_uses_users_bcrypt_and_unified_jwt(self):
    result = auth_router.register(
        schemas.MemberRegistration(
            email=" Member@Example.com ", name="Member", phone="+60 12-345 6789",
            password="member-pass", password_confirmation="member-pass",
        ), db=db,
    )
    user = db.query(models.User).filter_by(email="member@example.com").one()
    assert user.member_code.startswith("FL")
    assert user.phone == "60123456789"
    assert verify_password("member-pass", user.password_hash)
    assert result["access_token"].count(".") == 2

@pytest.mark.parametrize("identifier", ["member@example.com", "60123456789", "fl00000001"])
def test_login_accepts_email_phone_or_member_id(identifier):
    result = auth_router.login(
        schemas.AccountLogin(identifier=identifier, password="member-pass"), db=db
    )
    assert result["user"]["member_code"] == "FL00000001"

def test_inactive_and_wrong_password_share_generic_error():
    for body in (
        schemas.AccountLogin(identifier="inactive@example.com", password="right-pass"),
        schemas.AccountLogin(identifier="member@example.com", password="wrong-pass"),
    ):
        with pytest.raises(HTTPException) as error:
            auth_router.login(body, db=db)
        assert error.value.status_code == 401
        assert error.value.detail == "Invalid credentials"
```

Also test duplicate normalized email, duplicate normalized phone, password-confirmation mismatch, `get_membership_user` rejecting an admin-only account with HTTP 403, and `get_admin_user` accepting a membership-capable admin.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
python3 -m pytest tests/test_unified_accounts.py -q
```

Expected: FAIL because `AccountLogin`, unified registration, membership fields, and `get_membership_user` do not exist.

- [ ] **Step 3: Define unified schemas and authentication helpers**

Replace `UserLogin` and `MemberLogin` with:

```python
class AccountLogin(BaseModel):
    identifier: str
    password: str
```

Keep `MemberRegistration` as the public registration contract. In `auth.py`, add:

```python
def get_membership_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")
    if not current_user.member_code:
        raise HTTPException(status_code=403, detail="Membership profile required")
    return current_user
```

Delete `member_auth.py`. Do not add compatibility verification for PBKDF2 hashes because the approved local member records are disposable and production has only bcrypt user passwords.

- [ ] **Step 4: Implement canonical registration and login**

In `auth.py`, add the normalization helpers so routers and membership services share one implementation:

```python
def normalize_email(value: str) -> str:
    return (value or "").strip().lower()

def normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")
```

In `routers/auth.py`, import those helpers and add code generation and serialization:

```python
from auth import create_token, hash_password, normalize_email, normalize_phone, verify_password

def _generate_member_code(db: Session) -> str:
    for _ in range(20):
        code = f"FL{secrets.randbelow(100_000_000):08d}"
        if not db.query(models.User.id).filter(models.User.member_code == code).first():
            return code
    raise HTTPException(status_code=500, detail="Unable to generate unique Member ID")

def serialize_account(user: models.User) -> dict:
    return {
        "id": user.id, "email": user.email, "name": user.name,
        "is_admin": bool(user.is_admin), "member_code": user.member_code,
        "phone": user.phone, "is_active": bool(user.is_active),
        "account_type": "member" if user.member_code else "user",
    }
```

Registration validates required fields and confirmation, inserts `models.User(..., is_admin=False, member_code=_generate_member_code(db), password_hash=hash_password(body.password))`, converts `IntegrityError` to HTTP 409, and returns `create_token(user.id)`.

Login queries active users with:

```python
identifier = body.identifier.strip()
user = db.query(models.User).filter(
    or_(
        models.User.email.ilike(normalize_email(identifier)),
        models.User.phone == normalize_phone(identifier),
        models.User.member_code.ilike(identifier),
    ),
    models.User.is_active.is_(True),
).first()
```

It verifies only `auth.verify_password`, returns one JWT, and uses `Invalid credentials` for every failure. `/auth/me` returns `serialize_account(current_user)`.

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```bash
python3 -m pytest tests/test_unified_accounts.py -q
```

Expected: all unified account tests PASS.

- [ ] **Step 6: Commit the authentication unit**

```bash
git add backend/auth.py backend/schemas.py backend/routers/auth.py backend/member_auth.py tests/test_unified_accounts.py
git commit -m "feat: unify account registration and login"
```

---

### Task 3: Move Membership Operations Onto User Rows

**Files:**
- Modify: `backend/routers/memberships.py:1-530`
- Modify: `backend/routers/timetable.py`
- Modify: `tests/test_memberships.py`
- Modify: `tests/test_table_timers.py`

**Interfaces:**
- Consumes: `models.User`, `auth.get_membership_user`, `auth.hash_password`, and `auth.normalize_*` behavior from Task 2.
- Produces: membership resource routes backed exclusively by membership-capable `User` rows.
- Preserves: response field `member_id` and `/api/members/...` resource URLs.
- Removes: `/api/members/register`, `/api/members/login`, and all member-token dependencies.

- [ ] **Step 1: Update membership tests to construct unified users**

Replace every `models.Member(...)` fixture with:

```python
models.User(
    email="member@example.com",
    password_hash=hash_password("member-pass"),
    name="Member",
    is_admin=False,
    member_code="FL00000001",
    phone="60123456789",
    is_active=True,
    notes="",
)
```

Add assertions that the memberships router source has no `/register`, no `/login`, no `member_auth`, and no `models.Member`. Add a test that `member_me`, package, visit, and QR operations accept a membership-capable `User` and reject an admin-only `User` through `get_membership_user`.

- [ ] **Step 2: Run membership and timer tests to verify RED**

Run:

```bash
python3 -m pytest tests/test_memberships.py tests/test_table_timers.py -q
```

Expected: FAIL because router queries and relationships still use `models.Member`.

- [ ] **Step 3: Convert membership helpers and routes to `User`**

Rename type hints while keeping public helper names stable:

```python
def remaining_seconds_for_member(member: models.User) -> int: ...
def serialize_member(member: models.User) -> dict: ...
def search_members(db: Session, query: str, limit: int = 25) -> list[models.User]: ...
def find_member_by_code(db: Session, member_code: str) -> Optional[models.User]: ...
def resolve_active_member(db: Session, member_code: str) -> models.User: ...
```

Every membership query must use `models.User` plus `models.User.member_code.is_not(None)`. Search matches name, email, phone, and member code. Remove `create_member_record`, `register_member`, and `login_member` because Task 2 owns account creation and login.

Change `/me`, `/me/packages`, `/me/visits`, and `/me/qr` dependencies to `Depends(get_membership_user)`. Staff routes continue to use `get_admin_user` but fetch the target from `models.User` and return 404 unless `member_code` is populated.

Password edits call `auth.hash_password`. Duplicate email/phone errors remain HTTP 409. `serialize_member` returns the same membership payload, with `id` equal to `users.id`.

- [ ] **Step 4: Convert timetable lookups and relationships**

Replace every `db.query(models.Member)` with `db.query(models.User)` and require `member_code.is_not(None)` plus `is_active.is_(True)`. Keep request/response names such as `member_id` and `active_member_id` unchanged so frontend contracts do not change.

Ensure `record_member_visit_for_log` locks the unified user row:

```python
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
```

- [ ] **Step 5: Run membership and timer tests to verify GREEN**

Run:

```bash
python3 -m pytest tests/test_memberships.py tests/test_table_timers.py -q
```

Expected: all selected tests PASS with no reference to `models.Member` or member tokens.

- [ ] **Step 6: Commit the membership unit**

```bash
git add backend/routers/memberships.py backend/routers/timetable.py tests/test_memberships.py tests/test_table_timers.py
git commit -m "refactor: use users for membership records"
```

---

### Task 4: Collapse Favorites To One User Owner

**Files:**
- Modify: `backend/routers/favorites.py`
- Modify: `tests/test_member_favorites.py`

**Interfaces:**
- Consumes: the unified JWT and `models.Favorite.user_id` from Tasks 1-2.
- Produces: favorite list/toggle behavior for both admin-only and membership-capable users through `get_current_user`.
- Removes: `FavoritePrincipal`, member-token fallback, `_owner_filter`, and dynamic owner construction.

- [ ] **Step 1: Rewrite favorite tests for one principal type**

Create one admin-only user and one membership-capable user, call the router with each as `current_user`, and assert their favorites remain isolated:

```python
member_result = favorites.toggle_favorite(
    member_pattern.id, current_user=member_user, db=db
)
assert member_result["favorited"] is True
assert db.query(models.Favorite).filter_by(
    user_id=member_user.id, pattern_id=member_pattern.id
).one()

admin_result = favorites.toggle_favorite(
    admin_pattern.id, current_user=admin_user, db=db
)
assert admin_result["favorited"] is True
assert favorites.list_favorite_ids(current_user=member_user, db=db) == [member_pattern.id]
assert favorites.list_favorite_ids(current_user=admin_user, db=db) == [admin_pattern.id]
```

- [ ] **Step 2: Run favorite tests to verify RED**

Run:

```bash
python3 -m pytest tests/test_member_favorites.py -q
```

Expected: FAIL because the router still requires `FavoritePrincipal` and supports `member_id`.

- [ ] **Step 3: Implement the single-owner router**

Use `current_user: models.User = Depends(get_current_user)` in every route. Query with `models.Favorite.user_id == current_user.id`, and create rows with:

```python
models.Favorite(user_id=current_user.id, pattern_id=pattern_id)
```

Delete `FavoritePrincipal`, `get_current_principal`, `_owner_filter`, `_new_favorite`, imports from `member_auth`, and every `member_id` branch.

- [ ] **Step 4: Run favorite tests to verify GREEN**

Run:

```bash
python3 -m pytest tests/test_member_favorites.py -q
```

Expected: all favorite tests PASS and both account types use `user_id`.

- [ ] **Step 5: Commit the favorites unit**

```bash
git add backend/routers/favorites.py tests/test_member_favorites.py
git commit -m "refactor: use unified users for favorites"
```

---

### Task 5: Use One Browser Session And Login Surface

**Files:**
- Modify: `frontend/index.html`
- Modify: `tests/test_frontend_ux_safety.py`
- Modify: `tests/test_memberships.py`

**Interfaces:**
- Consumes: `{access_token, token_type, user}` from `/api/auth/register` and `/api/auth/login`.
- Produces: one `pc_token` and one `pc_user` session used by the whole SPA.
- Removes: `pc_member_token`, `pc_token_type`, member-first/admin-fallback login, and calls to `/members/login` or `/members/register`.

- [ ] **Step 1: Write frontend source-contract tests for one session**

Assert:

```python
assert "apiFetch('/auth/login'" in html
assert "apiFetch('/auth/register'" in html
assert "'/members/login'" not in html
assert "'/members/register'" not in html
assert "pc_member_token" not in html
assert "pc_token_type" not in html
assert "memberApiFetch" not in html
assert "localStorage.setItem('pc_token', token)" in html
assert "localStorage.setItem('pc_user', JSON.stringify(account))" in html
assert "member_code" in html
assert "Membership profile required" in html
```

Also assert one logout helper removes `pc_token` and `pc_user`, and the Membership portal receives the same account object as the navigation/header.

- [ ] **Step 2: Run frontend contract tests to verify RED**

Run:

```bash
python3 -m pytest tests/test_frontend_ux_safety.py tests/test_memberships.py -q
```

Expected: FAIL because the SPA still contains separate member token/session behavior.

- [ ] **Step 3: Implement unified fetch and session helpers**

Keep one authenticated fetch helper using `pc_token`. Replace the member helpers with:

```javascript
function storeAccountSession(account, token) {
  localStorage.setItem('pc_token', token);
  localStorage.setItem('pc_user', JSON.stringify(account));
  return account;
}

function clearAccountSession() {
  localStorage.removeItem('pc_token');
  localStorage.removeItem('pc_user');
}
```

On startup, call `/auth/me` once. If it succeeds, store the returned account as global state. If it fails, clear the session. Membership API requests use the same `apiFetch` and token.

- [ ] **Step 4: Point both authentication surfaces to `/auth`**

The main popup login sends:

```javascript
apiFetch('/auth/login', {
  method:'POST',
  body:JSON.stringify({ identifier:form.identifier, password:form.password }),
})
```

Registration sends the existing five fields to `/auth/register`. Remove the member-first request and admin fallback. Both flows call `storeAccountSession(data.user, data.access_token)`.

The Membership portal does not display a second login when a global account is present. If `user.member_code` is null, show a non-error state reading: `Membership profile required. Ask an administrator to add a phone number and Member ID to this account.` Otherwise load `/members/me`, packages, visits, and QR using the global token.

- [ ] **Step 5: Unify logout and navigation behavior**

Both the header and Membership portal call `clearAccountSession()` and clear global user state. Show Admin/Staff navigation when `user.is_admin` is true and membership content when `user.member_code` is populated; both can be true for one account.

- [ ] **Step 6: Run frontend contract tests to verify GREEN**

Run:

```bash
python3 -m pytest tests/test_frontend_ux_safety.py tests/test_memberships.py -q
```

Expected: all selected frontend tests PASS with no legacy member session keys or endpoints.

- [ ] **Step 7: Commit the frontend unit**

```bash
git add frontend/index.html tests/test_frontend_ux_safety.py tests/test_memberships.py
git commit -m "feat: use one account session across the site"
```

---

### Task 6: Add A Verified Production Backup Gate

**Files:**
- Modify: `scripts/deploy_lightsail_ubuntu.sh`
- Modify: `scripts/deploy_digitalocean_ubuntu.sh`
- Modify: `DEPLOYMENT.md`
- Modify: `DIGITALOCEAN_UBUNTU_DEPLOYMENT.md`
- Modify: `tests/test_lightsail_ssh_deploy.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: timestamped backups under `${APP_DIR}/backups/` before `compose up` runs migrations.
- Produces: deployment abort when a database exists but its backup cannot be opened and verified.
- Produces: `${APP_DIR}/.previous-deploy-commit` containing the checkout revision that was running before `git pull`.
- Consumes: Docker volume `${COMPOSE_PROJECT_NAME}_pindou_data`.

- [ ] **Step 1: Write deployment source-contract tests**

Assert the Lightsail and DigitalOcean scripts contain `backup_database`, invoke it before `deploy_stack`, create `${APP_DIR}/backups`, use Python's `sqlite3.Connection.backup`, and run `PRAGMA integrity_check` on the destination. Assert they record `.previous-deploy-commit` before pulling. Assert the docs include the generated backup path, `SECRET_KEY` rotation, and restore commands.

- [ ] **Step 2: Run deployment tests to verify RED**

Run:

```bash
python3 -m pytest tests/test_lightsail_ssh_deploy.py tests/test_migrations.py -q
```

Expected: FAIL because deployment currently starts containers without an automatic verified backup gate.

- [ ] **Step 3: Implement the backup function in both deployment scripts**

Install `python3` in the base package list. Before `git pull`, persist the currently deployed revision:

```bash
sudo_cmd git rev-parse HEAD | sudo_cmd tee "${APP_DIR}/.previous-deploy-commit" >/dev/null
```

Add this function, using the script's existing `sudo_cmd` wrapper:

```bash
backup_database() {
  local volume_name="${COMPOSE_PROJECT_NAME}_pindou_data"
  if ! sudo_cmd docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    log "No existing database volume; skipping backup"
    return
  fi

  local mountpoint database_path backup_dir backup_path
  mountpoint="$(sudo_cmd docker volume inspect "${volume_name}" --format '{{ .Mountpoint }}')"
  database_path="${mountpoint}/pindou.db"
  if [[ ! -f "${database_path}" ]]; then
    log "No existing SQLite database; skipping backup"
    return
  fi

  backup_dir="${APP_DIR}/backups"
  backup_path="${backup_dir}/pindou-$(date +'%Y%m%d-%H%M%S').db"
  sudo_cmd install -d -m 0700 "${backup_dir}"
  sudo_cmd python3 -c '
import sqlite3, sys
source, destination = sys.argv[1], sys.argv[2]
with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)
with sqlite3.connect(destination) as check:
    result = check.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    raise SystemExit(f"backup integrity check failed: {result}")
' "${database_path}" "${backup_path}"
  log "Verified database backup: ${backup_path}"
}
```

Call `backup_database` after `ensure_env_file` and before `deploy_stack`. Add a once-only persisted rotation function so later routine deployments do not repeatedly sign users out:

```bash
rotate_secret_for_unified_accounts_once() {
  local marker
  marker="$(grep '^UNIFIED_ACCOUNT_SECRET_ROTATED=' "${ENV_FILE}" | cut -d= -f2- || true)"
  if [[ "${marker}" == "true" ]]; then
    log "Unified-account signing-key rotation already completed"
    return
  fi
  set_env_value "SECRET_KEY" "$(openssl rand -hex 32)"
  set_env_value "UNIFIED_ACCOUNT_SECRET_ROTATED" "true"
  log "Rotated SECRET_KEY once for unified account migration"
}
```

Call it immediately after `backup_database` and before `deploy_stack`. The log states that rotation occurred but never prints the secret.

- [ ] **Step 4: Document backup, key rotation, and restoration**

Document that the migration release signs users out once. Add these exact rollback commands, where `BACKUP` is selected from the printed verified backup path:

```bash
cd /opt/pixelcraft
BACKUP="$(ls -1t /opt/pixelcraft/backups/pindou-*.db | head -n 1)"
PREVIOUS_COMMIT="$(cat /opt/pixelcraft/.previous-deploy-commit)"
sudo docker compose --project-name pixelcraft --env-file .env down
MOUNTPOINT="$(sudo docker volume inspect pixelcraft_pindou_data --format '{{ .Mountpoint }}')"
sudo install -m 0600 "${BACKUP}" "${MOUNTPOINT}/pindou.db"
sudo git checkout "${PREVIOUS_COMMIT}"
sudo docker compose --project-name pixelcraft --env-file .env up --build -d
```

The documentation tells the operator that `BACKUP` selects the newest verified backup and to set it to an older exact path when required. It warns never to use `docker compose down -v`.

- [ ] **Step 5: Run deployment tests to verify GREEN**

Run:

```bash
python3 -m pytest tests/test_lightsail_ssh_deploy.py tests/test_migrations.py -q
```

Expected: all selected tests PASS and source ordering proves backup precedes migration startup.

- [ ] **Step 6: Commit the deployment unit**

```bash
git add scripts/deploy_lightsail_ubuntu.sh scripts/deploy_digitalocean_ubuntu.sh DEPLOYMENT.md DIGITALOCEAN_UBUNTU_DEPLOYMENT.md tests/test_lightsail_ssh_deploy.py tests/test_migrations.py
git commit -m "ops: back up database before account migration"
```

---

### Task 7: Full Regression And End-To-End Verification

**Files:**
- Verify: all files changed in Tasks 1-6
- Modify only if a failing test exposes a requirement gap.

**Interfaces:**
- Consumes: unified schema, API, membership resources, favorites, frontend session, and deployment backup gate.
- Produces: requirement-by-requirement completion evidence and a verified local/public build.

- [ ] **Step 1: Search for forbidden legacy paths**

Run:

```bash
rg -n "models\.Member|member_auth|pc_member_token|pc_token_type|/members/login|/members/register|Favorite\.member_id" backend frontend tests
```

Expected: no application references; any migration fixture references are explicitly limited to constructing the disposable legacy schema.

- [ ] **Step 2: Run the complete automated suite**

Run:

```bash
python3 -m pytest -q
```

Expected: all tests PASS with zero failures.

- [ ] **Step 3: Compile backend and validate Alembic history**

Run:

```bash
python3 -m compileall -q backend
cd backend && APP_ENV=test python3 -m alembic -c alembic.ini history && cd ..
```

Expected: compilation exits 0 and history ends at `20260711_0003 (head)`.

- [ ] **Step 4: Test migration against disposable production-style SQLite data**

Create a temporary database containing the production-style `users`, `patterns`, and `favorites` tables, insert an admin with a known bcrypt hash, run `alembic upgrade head`, and query it to prove the ID, hash, and admin flag are unchanged and the membership columns are nullable.

- [ ] **Step 5: Rebuild the Docker stack with a disposable volume**

Run under a separate Compose project so the current local database is untouched:

```bash
SECRET_KEY="$(openssl rand -hex 32)" COMPOSE_PROJECT_NAME=pixelcraft_unified_test PORT=8081 docker compose up --build -d
```

Wait for `http://127.0.0.1:8081/api/patterns`, then register a member, sign in by email/phone/Member ID, verify `/api/members/me`, and verify an existing admin can still access an admin-only endpoint.

- [ ] **Step 6: Verify the browser journeys locally**

At `http://127.0.0.1:8081`, verify desktop and mobile widths:

- member registration returns one signed-in session;
- navigation to Membership shows the same account without another login;
- member QR, packages, visits, and saved patterns load;
- admin-only login shows admin navigation;
- an admin without `member_code` sees the membership-profile-required message rather than invalid credentials;
- one logout clears access everywhere.

- [ ] **Step 7: Verify through a temporary Cloudflare tunnel**

Expose `http://127.0.0.1:8081` with:

```bash
cloudflared tunnel --url http://127.0.0.1:8081 --no-autoupdate
```

Repeat unified login, Membership navigation, and `/api/patterns` checks through the generated HTTPS URL. Stop the tunnel after verification.

- [ ] **Step 8: Remove the disposable stack**

```bash
COMPOSE_PROJECT_NAME=pixelcraft_unified_test PORT=8081 docker compose down -v
```

Expected: only the disposable project and volumes are removed; the normal local project remains running.

- [ ] **Step 9: Record final status and commit any verification-only fixes**

Run:

```bash
git status --short
git log --oneline -8
```

If verification required code changes, rerun the affected focused test and the full suite, then commit only those files with:

```bash
git commit -m "fix: complete unified account verification"
```
