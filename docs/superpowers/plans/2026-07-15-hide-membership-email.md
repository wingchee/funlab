# Hide Membership Email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the admin Membership page from displaying, searching by, or editing account email addresses.

**Architecture:** Keep email data and authentication unchanged. Limit the change to the `MembershipPage` frontend state, search copy, render branches, and member-update request. A source-level frontend safety test protects the boundary without changing the backend API.

**Tech Stack:** React via Babel in `frontend/index.html`, Python `pytest`, Docker Compose.

## Global Constraints

- Do not delete or migrate stored email addresses.
- Do not change sign-in or backend authentication behaviour.
- Membership lookup and display use only name, phone, and Member ID.
- The Membership page must not submit `email` in its member-update request.

---

### Task 1: Remove email from the Membership page

**Files:**
- Modify: `tests/test_frontend_ux_safety.py`
- Modify: `frontend/index.html:3071-3525`

**Interfaces:**
- Consumes: `MembershipPage({ user, onLogout })` and its existing `apiFetch('/members/search')` and `apiFetch(`/members/${selected.id}`)` calls.
- Produces: A Membership page that uses name, phone, and Member ID without rendering or sending account email data.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_frontend_ux_safety.py`:

```python
def test_membership_page_hides_email_from_staff_workflows():
    html = read_frontend()
    membership_source = html[
        html.index("function MembershipPage({ user, onLogout })"):
        html.index("function MemberPortalPage(")
    ]

    assert 'placeholder="Name, phone, or Member ID"' in membership_source
    assert 'placeholder="Name, email, phone, or Member ID"' not in membership_source
    assert 'member.email' not in membership_source
    assert 'selected.email' not in membership_source
    assert 'email:editForm.email' not in membership_source
    assert 'placeholder="Email" type="email"' not in membership_source
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py::test_membership_page_hides_email_from_staff_workflows -v`

Expected: FAIL because `MembershipPage` still contains the email search placeholder, visible member email expressions, and email update field.

- [ ] **Step 3: Write the minimal implementation**

In `frontend/index.html`, make these exact MembershipPage changes:

```jsx
const [editForm, setEditForm] = useState({ name:'', phone:'', password:'', is_active:true, notes:'' });
```

```jsx
setEditForm({
  name:selected.name || '',
  phone:selected.phone || '',
  password:'',
  is_active:selected.is_active !== false,
  notes:selected.notes || '',
});
```

Use dependencies that omit `selected?.email`:

```jsx
}, [selected?.id, selected?.name, selected?.phone, selected?.is_active, selected?.notes]);
```

Omit the email property from the member update body:

```jsx
body:JSON.stringify({
  name:editForm.name,
  phone:editForm.phone,
  password:editForm.password,
  is_active:editForm.is_active,
  notes:editForm.notes,
}),
```

Replace the visible search placeholder and account-only list fallback:

```jsx
placeholder="Name, phone, or Member ID"
```

```jsx
{member.member_code ? `${member.member_code} · ${member.phone}` : 'Account only'}
```

Remove the selected email display and the email input from the Member Profile form. Keep name, phone, password, notes, active-status, save, and membership-removal controls unchanged.

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py -v`

Expected: PASS, including `test_membership_page_hides_email_from_staff_workflows` and existing frontend safety checks.

- [ ] **Step 5: Build and verify the Docker frontend**

Run: `docker compose up --build -d frontend && docker compose ps frontend && curl -fsS -o /dev/null -w 'frontend_http=%{http_code}\n' http://localhost/`

Expected: frontend service is running and the final output is `frontend_http=200`.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html tests/test_frontend_ux_safety.py
git -c commit.gpgsign=false commit -m "fix: hide email from membership page"
```

## Plan Self-Review

- Spec coverage: Task 1 removes email from visible list/detail UI, search copy and workflow, profile editor, and update request while leaving stored emails and authentication untouched.
- Placeholder scan: no placeholders or deferred implementation steps remain.
- Type consistency: all changes remain within the existing JavaScript `MembershipPage` state and `apiFetch` request contract.
