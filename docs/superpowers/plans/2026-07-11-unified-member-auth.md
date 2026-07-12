# Unified Member Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing `Member` account the single customer identity for main-site sign-in, registration, Membership data, and saved patterns while preserving separate administrator accounts.

**Architecture:** Add member email and member-owned favorites through an Alembic migration, centralize member token/password operations in `member_auth.py`, and let the favorites router resolve either a user or member bearer token. The React SPA stores a member token as both the active site token and membership token, while administrator login continues through the existing auth endpoint.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, SQLite/PostgreSQL-compatible schema changes, React 18 via Babel, Python `unittest`/`pytest`.

## Global Constraints

- `Member` is the sole customer identity; `User` remains the administrator/legacy operational identity.
- Registration requires email, name, phone, password, and password confirmation.
- Member login accepts email, normalized phone number, or Member ID.
- Remove staff-side member creation while preserving search, QR scanning, package management, editing, and table check-in.
- Existing user-owned favorites and members without email must survive migration.
- Invalid credentials must not disclose whether a member exists.
- Follow red-green-refactor for every behavior change.

---

### Task 1: Persist Member Email And Member-Owned Favorites

**Files:**
- Modify: `backend/models.py`
- Create: `backend/alembic/versions/20260711_0002_unified_member_auth.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `Member.email: Optional[str]`, `Favorite.member_id: Optional[int]`, nullable `Favorite.user_id`, and `Member.favorites` relationship.
- Preserves: existing `users`, members without email, and user-owned favorite rows.

- [ ] **Step 1: Write failing migration tests**

Extend the fresh-schema test to assert `email` exists on `members`, `member_id` exists on `favorites`, `favorites.user_id` is nullable, and both unique member-email and member-favorite indexes exist. Extend the legacy migration test with `users`, `patterns`, and `favorites` rows and assert the old favorite remains user-owned after upgrade:

```python
member_columns = {
    row[1]: row for row in connection.execute("PRAGMA table_info('members')")
}
favorite_columns = {
    row[1]: row for row in connection.execute("PRAGMA table_info('favorites')")
}
self.assertIn("email", member_columns)
self.assertIn("member_id", favorite_columns)
self.assertEqual(favorite_columns["user_id"][3], 0)
self.assertEqual(
    connection.execute(
        "SELECT user_id, member_id, pattern_id FROM favorites WHERE id = 1"
    ).fetchone(),
    (1, None, 1),
)
self.assertEqual(
    connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
    "20260711_0002",
)
```

- [ ] **Step 2: Run migration tests and verify RED**

Run: `python3 -m pytest tests/test_migrations.py -q`

Expected: FAIL because revision `20260711_0002`, `members.email`, and `favorites.member_id` do not exist.

- [ ] **Step 3: Add ORM fields and migration**

Add these model fields and relationships:

```python
class Member(Base):
    email = Column(String, unique=True, nullable=True, index=True)
    favorites = relationship("Favorite", back_populates="member", cascade="all, delete-orphan")

class Favorite(Base):
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True, index=True)
    member = relationship("Member", back_populates="favorites")
```

Create revision `20260711_0002` with `down_revision = "20260710_0001"`. In `upgrade()`, add nullable `members.email`, normalize populated values with `LOWER(TRIM(email))`, reject duplicate populated emails, create unique index `ix_members_email`, add nullable `favorites.member_id` with FK to `members.id`, make `favorites.user_id` nullable with batch mode, and create unique index `uq_favorites_member_pattern` on `(member_id, pattern_id)`. In `downgrade()`, remove the new indexes/columns and restore non-null `favorites.user_id`; document that downgrade requires no member-owned favorite rows.

- [ ] **Step 4: Run migration tests and verify GREEN**

Run: `python3 -m pytest tests/test_migrations.py -q`

Expected: all migration tests PASS.

- [ ] **Step 5: Commit the schema unit**

```bash
git add backend/models.py backend/alembic/versions/20260711_0002_unified_member_auth.py tests/test_migrations.py
git commit -m "feat: add member email and favorite ownership"
```

### Task 2: Implement Complete Member Registration And Login

**Files:**
- Create: `backend/member_auth.py`
- Modify: `backend/schemas.py`
- Modify: `backend/routers/memberships.py`
- Modify: `tests/test_memberships.py`

**Interfaces:**
- Produces: `normalize_email(value: str) -> str`, `create_member_token(member_id: int) -> str`, `member_from_token(token: str, db: Session) -> Optional[Member]`, and `current_member_from_token(...) -> Member` in `member_auth.py`.
- Produces: `MemberRegistration(email, name, phone, password, password_confirmation)` request model.
- Changes: `create_member_record(..., email: str = "")` and member serialization includes `email`.

- [ ] **Step 1: Write failing registration and login tests**

Add focused tests that call `register_member` and `login_member` directly:

```python
def test_registration_requires_matching_passwords_and_unique_normalized_email(self):
    db = self._session()
    memberships = self._memberships()
    body = schemas.MemberRegistration(
        email=" Alice@Example.com ",
        name="Alice Tan",
        phone="+60 12-345 6789",
        password="safe-password",
        password_confirmation="safe-password",
    )
    response = memberships.register_member(body, db=db)
    self.assertEqual(response["member"]["email"], "alice@example.com")
    with self.assertRaises(HTTPException) as mismatch:
        memberships.register_member(
            schemas.MemberRegistration(
                email="other@example.com", name="Other", phone="60111111111",
                password="one-password", password_confirmation="different-password",
            ),
            db=db,
        )
    self.assertEqual(mismatch.exception.status_code, 400)
    with self.assertRaises(HTTPException) as duplicate:
        memberships.register_member(
            schemas.MemberRegistration(
                email="ALICE@example.com", name="Duplicate", phone="60122222222",
                password="safe-password", password_confirmation="safe-password",
            ),
            db=db,
        )
    self.assertEqual(duplicate.exception.status_code, 409)

def test_member_can_login_with_email_phone_or_member_id(self):
    db = self._session()
    memberships = self._memberships()
    registered = memberships.register_member(
        schemas.MemberRegistration(
            email="login@example.com", name="Login Member", phone="+60 12-000 0000",
            password="safe-password", password_confirmation="safe-password",
        ),
        db=db,
    )
    code = registered["member"]["member_code"]
    for identifier in ["LOGIN@EXAMPLE.COM", "60120000000", code.lower()]:
        result = memberships.login_member(
            schemas.MemberLogin(identifier=identifier, password="safe-password"), db=db
        )
        self.assertEqual(result["member"]["member_code"], code)
```

Add a source assertion that `@router.post("")` and `def admin_create_member` are absent from `memberships.py`.

- [ ] **Step 2: Run focused membership tests and verify RED**

Run: `python3 -m pytest tests/test_memberships.py -q`

Expected: FAIL because `MemberRegistration`, email storage/login, confirmation validation, and endpoint removal are missing.

- [ ] **Step 3: Centralize member auth and implement contracts**

Move the existing PBKDF2 hash/verify and HMAC member-token logic from `memberships.py` to `member_auth.py`. Expose safe token resolution:

```python
def member_from_token(token: str, db: Session) -> Optional[models.Member]:
    try:
        member_id = decode_member_token(token)
    except HTTPException:
        return None
    return db.query(models.Member).filter(
        models.Member.id == member_id,
        models.Member.is_active.is_(True),
    ).first()
```

Add schemas:

```python
class MemberRegistration(BaseModel):
    email: str
    name: str
    phone: str
    password: str
    password_confirmation: str

class MemberUpdate(BaseModel):
    email: str = ""
    name: str = ""
    phone: str = ""
    password: str = ""
    is_active: Optional[bool] = None
    notes: str = ""
```

Normalize email with `value.strip().lower()`. Registration validates all five values, matching passwords, duplicate email, and duplicate phone before calling `create_member_record`. Login queries active members by case-insensitive email, case-insensitive Member ID, or normalized phone. Remove the admin `POST /members` route. Let admin update set and uniquely validate a normalized email. Return generic `Invalid member credentials` for login failures.

- [ ] **Step 4: Run focused membership tests and verify GREEN**

Run: `python3 -m pytest tests/test_memberships.py -q`

Expected: all membership tests PASS.

- [ ] **Step 5: Commit the membership-auth unit**

```bash
git add backend/member_auth.py backend/schemas.py backend/routers/memberships.py tests/test_memberships.py
git commit -m "feat: unify member registration and login"
```

### Task 3: Support Saved Patterns For Member Sessions

**Files:**
- Modify: `backend/routers/favorites.py`
- Create: `tests/test_member_favorites.py`

**Interfaces:**
- Consumes: `member_auth.member_from_token(token, db)` from Task 2.
- Produces: `FavoritePrincipal(kind: Literal["user", "member"], id: int)` and a dependency that accepts either existing user JWTs or member tokens.

- [ ] **Step 1: Write failing favorite ownership tests**

Create an in-memory database test that makes one `User`, one `Member`, and one `Pattern`. Generate their real tokens, call the favorites router functions through `TestClient` or dependency overrides, and assert:

```python
self.assertEqual(member_toggle.status_code, 200)
favorite = db.query(models.Favorite).filter_by(pattern_id=pattern.id).one()
self.assertEqual(favorite.member_id, member.id)
self.assertIsNone(favorite.user_id)
self.assertEqual(member_ids.json(), [pattern.id])

self.assertEqual(user_toggle.status_code, 200)
user_favorite = db.query(models.Favorite).filter_by(
    user_id=user.id, pattern_id=second_pattern.id
).one()
self.assertIsNone(user_favorite.member_id)
```

Also assert an invalid token receives 401 and a second toggle removes only the current principal's favorite.

- [ ] **Step 2: Run favorite tests and verify RED**

Run: `python3 -m pytest tests/test_member_favorites.py -q`

Expected: FAIL because member bearer tokens are rejected and `Favorite.member_id` is unused.

- [ ] **Step 3: Implement dual-principal favorite resolution**

Use one `HTTPBearer(auto_error=False)` dependency. Try the existing `_get_user_from_token`; if it returns a user, produce `FavoritePrincipal("user", user.id)`. Otherwise try `member_from_token`; if it returns a member, produce `FavoritePrincipal("member", member.id)`. Raise 401 if neither resolves.

Build the ownership predicate once:

```python
def _owner_filter(principal: FavoritePrincipal):
    if principal.kind == "member":
        return models.Favorite.member_id == principal.id
    return models.Favorite.user_id == principal.id

def _new_favorite(principal: FavoritePrincipal, pattern_id: int):
    values = {"pattern_id": pattern_id}
    values[f"{principal.kind}_id"] = principal.id
    return models.Favorite(**values)
```

Use these helpers in list, IDs, lookup, create, and delete paths. Preserve the shared pattern favorite count behavior.

- [ ] **Step 4: Run favorite and membership tests and verify GREEN**

Run: `python3 -m pytest tests/test_member_favorites.py tests/test_memberships.py -q`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the favorites unit**

```bash
git add backend/routers/favorites.py tests/test_member_favorites.py
git commit -m "feat: support member-owned saved patterns"
```

### Task 4: Unify Main Popup And Membership Frontend Sessions

**Files:**
- Modify: `frontend/index.html`
- Modify: `tests/test_memberships.py`
- Modify: `tests/test_frontend_ux_safety.py`

**Interfaces:**
- Consumes: member register/login response `{access_token, token_type, member}`.
- Produces: `LoginModal` with `login`/`register` modes and `onMemberLogin(member, token)` callback.
- Produces: shared `pc_token`, `pc_token_type`, and `pc_member_token` browser session keys; `pc_token_type` is `member` or `user`.

- [ ] **Step 1: Write failing frontend contract tests**

Assert the source contains the five registration fields and shared member endpoints/session keys:

```python
self.assertIn("const [mode, setMode] = useState('login')", html)
self.assertIn("passwordConfirmation", html)
self.assertIn("email, name, phone, password, password_confirmation", html)
self.assertIn("'/members/register'", html)
self.assertIn("'/members/login'", html)
self.assertIn("localStorage.setItem('pc_token_type', 'member')", html)
self.assertIn("localStorage.setItem('pc_member_token', token)", html)
self.assertIn("Email, phone, or Member ID", html)
self.assertNotIn(">Create Member</div>", html)
self.assertNotIn("const [createForm, setCreateForm]", html)
self.assertNotIn("const createMember = async", html)
self.assertNotIn("Select or create a member.", html)
```

Also assert both registration surfaces send `password_confirmation` and that member logout removes all three member session keys without removing a valid administrator token from an unrelated portal action.

- [ ] **Step 2: Run frontend contract tests and verify RED**

Run: `python3 -m pytest tests/test_memberships.py tests/test_frontend_ux_safety.py -q`

Expected: FAIL because the popup has no registration mode, sessions are split, confirmation is absent, and staff creation remains.

- [ ] **Step 3: Implement shared fetch/session helpers**

Change `apiFetch` to keep reading `pc_token`; change `memberApiFetch` to prefer `pc_member_token` and fall back to `pc_token` only when `pc_token_type === 'member'`. Add helpers:

```javascript
function storeMemberSession(member, token) {
  localStorage.setItem('pc_token', token);
  localStorage.setItem('pc_token_type', 'member');
  localStorage.setItem('pc_member_token', token);
  return { ...member, is_admin:false, account_type:'member' };
}

function clearMemberSession() {
  localStorage.removeItem('pc_member_token');
  if (localStorage.getItem('pc_token_type') === 'member') {
    localStorage.removeItem('pc_token');
    localStorage.removeItem('pc_token_type');
  }
}
```

On app mount, use `pc_token_type` to call `/members/me` for member sessions or `/auth/me` for user/admin sessions. Member login updates global `user`, loads favorite IDs, and leaves the Membership page able to use the same token.

- [ ] **Step 4: Replace the popup with sign-in/register modes**

Keep administrator fallback only in login mode: submit `/members/login` first, and if it returns 401 submit `/auth/login` using the same identifier as email. Registration validates all fields and matching passwords before sending:

```javascript
{
  email: form.email,
  name: form.name,
  phone: form.phone,
  password: form.password,
  password_confirmation: form.passwordConfirmation,
}
```

On successful member response, call `onMemberLogin(data.member, data.access_token)`. Display backend `detail` for duplicate registration and local confirmation errors. Label sign-in identifier `Email, phone, or Member ID`.

- [ ] **Step 5: Update Membership portal and remove staff creation**

Give `MemberPortalPage` an `onMemberLogin` callback. Add email and confirm-password fields to its register mode, send the same registration payload, and call the callback after storing the member session. Its logout calls `clearMemberSession` and informs the parent so the navbar returns to signed-out state.

Delete `createForm`, `createMember`, and the complete Create Member panel from `MembershipPage`. Change the empty detail copy to `Select a member.` Keep staff search, QR scanner, package, edit, and check-in controls unchanged.

- [ ] **Step 6: Run frontend contract tests and verify GREEN**

Run: `python3 -m pytest tests/test_memberships.py tests/test_frontend_ux_safety.py -q`

Expected: all selected tests PASS.

- [ ] **Step 7: Run the complete automated suite**

Run: `python3 -m pytest -q`

Expected: all tests PASS with no failures.

- [ ] **Step 8: Verify the running app through HTTPS**

Open the active Cloudflare tunnel in a desktop viewport and a mobile viewport. Confirm:

- Main popup switches between Sign In and Register.
- Register visibly contains email, name, phone, password, and confirm password.
- Password mismatch blocks submission.
- A new member stays signed in when navigating from Home to Membership.
- The same member can save a pattern and see it under Saved.
- Administrator login still exposes Admin and Staff Dashboard.
- Staff Dashboard has no Create Member panel and retains search, QR scan, package, edit, and check-in controls.

- [ ] **Step 9: Commit the frontend unit**

```bash
git add frontend/index.html tests/test_memberships.py tests/test_frontend_ux_safety.py
git commit -m "feat: unify site and membership sign in"
```

### Task 5: Completion Audit

**Files:**
- Verify: `docs/superpowers/specs/2026-07-11-unified-member-auth-design.md`
- Verify: all files modified in Tasks 1-4

**Interfaces:**
- Consumes: the complete implementation and test output.
- Produces: requirement-by-requirement completion evidence.

- [ ] **Step 1: Audit every explicit requirement**

Use source, migration schema inspection, API tests, frontend tests, and browser behavior to prove each numbered user requirement and each design constraint. Treat any missing or indirect evidence as incomplete and fix it before continuing.

- [ ] **Step 2: Run final verification from a clean command invocation**

Run: `python3 -m pytest -q`

Expected: full suite PASS.

- [ ] **Step 3: Record final worktree status**

Run: `git status --short`

Expected: only pre-existing unrelated changes or intentionally uncommitted files remain; no generated database or cache files are staged.
