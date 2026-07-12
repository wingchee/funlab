# Admin-Managed Member Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace public member registration with admin-created members, private balance links, and Funlab-branded QR codes.

**Architecture:** A unique opaque `balance_access_token` on each membership-bearing user grants restricted public balance access. The membership router owns creation, token rotation, and QR generation; the SPA adds an admin creation view and a no-login `/member/<token>` page.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite, qrcode/Pillow, React JSX, pytest, Docker Compose.

## Global Constraints

- Remove public registration UI and `POST /api/auth/register`; retain existing login.
- Admin creation accepts only a non-empty name and normalized unique phone.
- Every row with `member_code` has a unique opaque balance token; non-members have none.
- Public balance responses disclose only name, Member ID, remaining seconds, and package summaries; missing, inactive, revoked, and non-member links return 404.
- Regeneration invalidates the prior URL and QR immediately.
- A balance QR encodes `<origin>/member/<token>`, uses high error correction, and has a Funlab logo at no more than 20% of image width.
- Existing Member ID check-in QR APIs and table behavior stay unchanged.

---

### Task 1: Persist member balance tokens

**Files:**
- Create: `backend/alembic/versions/20260712_0004_admin_managed_member_links.py`
- Modify: `backend/models.py`
- Modify: `backend/schemas.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `User.balance_access_token: str | None` and `MemberCreate(name: str, phone: str)`.

- [ ] **Step 1: Write the failing migration test**

```python
def test_upgrade_backfills_unique_balance_tokens_for_members_only():
    # Seed revision 20260711_0003 with one member and one non-member, upgrade head.
    assert isinstance(member_token, str) and len(member_token) >= 32
    assert non_member_token is None
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE users SET balance_access_token=? WHERE id=2", (member_token,))
```

- [ ] **Step 2: Verify red**

Run: `python3 -m pytest tests/test_migrations.py -k balance_token -v`

Expected: FAIL because the column and revision are absent.

- [ ] **Step 3: Implement the migration and model**

Add this field beside `member_code`:

```python
balance_access_token = Column(String, unique=True, nullable=True, index=True)
```

Create revision `20260712_0004` with `down_revision = "20260711_0003"`. Add the nullable column and a unique index. Backfill only `member_code IS NOT NULL` rows with `secrets.token_urlsafe(32)`, retrying a collision; leave non-members null. Downgrade drops the index then column. Replace the prior `MemberCreate` declaration with:

```python
class MemberCreate(BaseModel):
    name: str
    phone: str
```

- [ ] **Step 4: Verify green**

Run: `python3 -m pytest tests/test_migrations.py tests/test_unified_accounts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260712_0004_admin_managed_member_links.py backend/models.py backend/schemas.py tests/test_migrations.py tests/test_unified_accounts.py
git commit -m "feat: add private member balance tokens"
```

### Task 2: Add secure member-link and QR APIs

**Files:**
- Create: `backend/assets/funlab-logo.jpeg` (copy of `frontend/funlab-logo.jpeg`)
- Modify: `backend/routers/auth.py`
- Modify: `backend/routers/memberships.py`
- Modify: `tests/test_memberships.py`
- Modify: `tests/test_unified_accounts.py`

**Interfaces:**
- Produces: `POST /api/members`, `GET /api/members/public/{token}`, `POST /api/members/{id}/balance-link/regenerate`, and `GET /api/members/{id}/balance-qr?origin=`.

- [ ] **Step 1: Write the failing router tests**

```python
created = memberships.admin_create_member(schemas.MemberCreate(name="Ari", phone="+61 412 345 678"), admin=admin, db=db)
assert created["member_code"].startswith("FL")
assert len(created["balance_access_token"]) >= 32
public = memberships.public_member_balance(created["balance_access_token"], db=db)
assert set(public) == {"name", "member_code", "remaining_seconds", "packages"}
old = created["balance_access_token"]
replacement = memberships.regenerate_member_balance_link(created["id"], admin=admin, db=db)
with pytest.raises(HTTPException):
    memberships.public_member_balance(old, db=db)
assert replacement["balance_access_token"] != old
```

Decode a generated `balance-qr?origin=https://members.example` PNG using `cv2.QRCodeDetector` and assert its data is `https://members.example/member/<token>`. Assert the centered logo plate differs from black QR modules. Assert public registration returns 404.

- [ ] **Step 2: Verify red**

Run: `python3 -m pytest tests/test_memberships.py tests/test_unified_accounts.py -k 'balance or public or qr or register' -v`

Expected: FAIL because these APIs do not exist and registration remains enabled.

- [ ] **Step 3: Implement the API surface**

Remove `register` and `MemberRegistration` use from `backend/routers/auth.py`; retain `login` and `/me`. Add:

```python
def _generate_balance_access_token(db: Session) -> str:
    for _ in range(20):
        token = secrets.token_urlsafe(32)
        if not db.query(models.User.id).filter(models.User.balance_access_token == token).first():
            return token
    raise HTTPException(status_code=500, detail="Unable to generate private balance link")
```

Admin creation normalizes/uniquely validates phone, assigns the generated Member ID and token, and uses `email=f"member-{token[:24]}@members.funlab.invalid"` with `hash_password(secrets.token_urlsafe(32))`. Roll back an `IntegrityError` as 409. Only admin creation/regeneration responses include `balance_access_token`.

`public_member_balance` filters by token, `member_code IS NOT NULL`, and active status; return exactly:

```python
{"name": member.name, "member_code": member.member_code,
 "remaining_seconds": remaining_seconds_for_member(member),
 "packages": [{"package_name": item.package_name, "remaining_seconds": int(item.remaining_seconds or 0)} for item in sorted(member.packages, key=lambda item: item.id)]}
```

Validate `origin` with `urlparse`: scheme is `http`/`https` and `netloc` is non-empty. Copy the logo asset. Generate balance QR with `qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)`, overlay a centered white plate and the logo at <=20% width. Do not alter `_member_qr_response` or check-in QR endpoints.

- [ ] **Step 4: Verify green**

Run: `python3 -m pytest tests/test_memberships.py tests/test_unified_accounts.py tests/test_security_config.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/assets/funlab-logo.jpeg backend/routers/auth.py backend/routers/memberships.py tests/test_memberships.py tests/test_unified_accounts.py
git commit -m "feat: add admin managed member balance links"
```

### Task 3: Add admin creation and public balance UI

**Files:**
- Modify: `frontend/index.html`
- Modify: `tests/test_frontend_ux_safety.py`

**Interfaces:**
- Consumes: Task 2 APIs.
- Produces: Sign-in-only modal, admin Add Member view, and `/member/<token>` public balance route.

- [ ] **Step 1: Write failing source-safety assertions**

```python
assert "apiFetch('/auth/register'" not in html
assert "Create Membership" not in html
assert "function AddMemberPage" in html
assert "apiFetch('/members'" in html
assert "function PublicMemberBalancePage" in html
assert "apiFetch(`/members/public/${token}`)" in html
assert "window.location.pathname.startsWith('/member/')" in html
assert "balance-qr?origin=" in html
```

- [ ] **Step 2: Verify red**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py -k 'member or registration' -v`

Expected: FAIL because registration and the new page components still exist/missing respectively.

- [ ] **Step 3: Implement the approved UX**

Make `LoginModal` identifier/password only. Add `AddMemberPage` inside staff Membership: Name and Phone submit exactly `{name, phone}` to `POST /members`; successful creation selects the returned member. Keep promotion for legacy account-only rows.

For a selected member, show `window.location.origin + '/member/' + selected.balance_access_token`, Copy Link, Download QR (fetch `/members/${selected.id}/balance-qr?origin=${encodeURIComponent(window.location.origin)}`), and Regenerate Link (confirm, call API, replace token, revoke prior blob URL).

Before standard app routing, detect `window.location.pathname.startsWith('/member/')`; extract the last path segment as `token` and render `PublicMemberBalancePage`. Fetch `/members/public/${token}` without authentication. Display only name, Member ID, remaining hours, and packages; show a neutral unavailable state for a non-OK response.

- [ ] **Step 4: Verify green and build**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py tests/test_frontend_mobile_ux.py -v`

Expected: PASS.

Run: `docker compose build frontend backend`

Expected: both images build successfully.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html tests/test_frontend_ux_safety.py
git commit -m "feat: add member balance link experience"
```

### Task 4: Verify the public-link lifecycle end to end

**Files:**
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_memberships.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: migration and link-revocation integration evidence.

- [ ] **Step 1: Write the failing lifecycle test**

```python
def test_public_balance_link_lifecycle_after_upgrade(self):
    db = self._session()
    memberships = self._memberships()
    admin = models.User(
        email="owner@example.com", password_hash=hash_password("admin-pass"),
        name="Owner", is_admin=True, is_active=True, notes="",
    )
    db.add(admin)
    db.commit()
    created = memberships.admin_create_member(
        schemas.MemberCreate(name="Ari", phone="+61 412 345 678"), _=admin, db=db,
    )
    member = db.query(models.User).filter_by(id=created["id"]).one()
    memberships.add_package_record(db, member, "Ten hours", 10 * 60 * 60)
    before = memberships.public_member_balance(created["balance_access_token"], db=db)
    rotated = memberships.regenerate_member_balance_link(member.id, _=admin, db=db)
    with self.assertRaises(HTTPException) as raised:
        memberships.public_member_balance(created["balance_access_token"], db=db)
    self.assertEqual(raised.exception.status_code, 404)
    after = memberships.public_member_balance(rotated["balance_access_token"], db=db)
    self.assertEqual(after["remaining_seconds"], before["remaining_seconds"])
```

- [ ] **Step 2: Verify red**

Run: `python3 -m pytest tests/test_migrations.py tests/test_memberships.py -k public_balance_link_lifecycle -v`

Expected: FAIL before the token, creation, and public-balance APIs exist.

- [ ] **Step 3: Add the lifecycle assertion to `MembershipTests`**

Add the exact test above to `tests/test_memberships.py`; do not add production behavior beyond Tasks 1-3.

- [ ] **Step 4: Verify complete system**

Run: `python3 -m pytest`

Expected: PASS.

Run: `docker compose up --build -d`

Expected: backend is healthy and frontend serves the new pages.

- [ ] **Step 5: Commit**

```bash
git add tests/test_migrations.py tests/test_memberships.py
git commit -m "test: cover member balance link lifecycle"
```
