# Remove Admin Member Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show administrators only the staff Membership dashboard, while preserving the member portal for non-admin users.

**Architecture:** Simplify `MembershipPage` by removing its admin-only membership mode state and member-mode branch. The existing non-admin early return to `MemberPortalPage` remains the sole portal entry within this component.

**Tech Stack:** React JSX in `frontend/index.html`; Python `pytest` static frontend assertions; Docker Compose frontend build.

## Global Constraints

- Admins see the staff dashboard and Add Member view only.
- Non-admin users continue to render `MemberPortalPage`.
- Do not change API calls, data models, public balance links, QR features, or table check-in behavior.

---

### Task 1: Remove the administrator portal switcher

**Files:**
- Modify: `frontend/index.html:3071-3472`
- Modify: `tests/test_frontend_ux_safety.py`

**Interfaces:**
- Consumes: `isAdmin`, `staffView`, and the existing non-admin `MemberPortalPage` return.
- Produces: An admin-only staff dashboard with no member-portal switcher or embedded portal branch.

- [ ] **Step 1: Write the failing regression test**

Add this test:

```python
def test_admin_membership_page_does_not_embed_member_portal():
    html = read_frontend()
    membership_source = html[
        html.index("function MembershipPage({ user, onLogout })"):
        html.index("function MemberPortalPage(")
    ]

    assert "const [membershipMode" not in membership_source
    assert "['member', 'Member Portal']" not in membership_source
    assert "<MemberPortalPage user={user} onLogout={onLogout} embedded/>" not in membership_source
    assert "if (!isAdmin)" in membership_source
    assert "<MemberPortalPage user={user} onLogout={onLogout}/>" in membership_source
```

- [ ] **Step 2: Verify red**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py::test_admin_membership_page_does_not_embed_member_portal -v`

Expected: FAIL because `MembershipPage` still has `membershipMode`, the Member Portal switcher button, and the embedded portal branch.

- [ ] **Step 3: Implement the minimal JSX removal**

Delete the `membershipMode` state, its non-admin mode-reset effect, the `if (membershipMode === 'member')` branch, and both Staff Dashboard / Member Portal segmented-switcher blocks. Keep this non-admin branch unchanged:

```jsx
if (!isAdmin) {
  return <MemberPortalPage user={user} onLogout={onLogout}/>;
}
```

Keep the existing `staffView === 'add-member'` branch, staff header, Add Member button, Refresh button, member search, QR, balance-link, package, and check-in controls unchanged.

- [ ] **Step 4: Verify green and build**

Run: `python3 -m pytest tests/test_frontend_ux_safety.py tests/test_frontend_mobile_ux.py -v`

Expected: PASS.

Run: `docker compose build frontend`

Expected: frontend image builds successfully.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html tests/test_frontend_ux_safety.py
git -c commit.gpgsign=false commit -m "fix: remove admin member portal"
```
