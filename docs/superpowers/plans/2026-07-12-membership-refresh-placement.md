# Membership Refresh Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the staff Membership Refresh button to the left of the Staff Dashboard / Member Portal switcher.

**Architecture:** Keep the existing inline wrapping flex header-action container in `MembershipPage`. Reorder its two existing JSX children only: the Refresh button first, then the mode-switcher container. A focused static frontend safety test locks the source order without adding a new client dependency.

**Tech Stack:** React JSX embedded in `frontend/index.html`; Python `pytest` static frontend assertions; Docker Compose frontend image build.

## Global Constraints

- Change only the staff Membership header control order.
- Preserve the existing Refresh callback, loading label, mode-switch callbacks, styles, and flex-wrap behavior.
- Do not alter API calls, account data, or the member-facing embedded portal header.

---

### Task 1: Reorder the staff Membership header controls

**Files:**
- Modify: `tests/test_frontend_ux_safety.py`
- Modify: `frontend/index.html:3321-3334`

**Interfaces:**
- Consumes: The existing `search('')` Refresh callback and `membershipMode` / `setMembershipMode` switcher state in `MembershipPage`.
- Produces: The same interactive controls, with the Refresh button preceding the switcher in the staff-header flex child order.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_frontend_ux_safety.py`:

```python
def test_membership_staff_header_places_refresh_before_mode_switcher():
    html = read_frontend()
    staff_header_start = html.index(
        "Search members, scan QR codes, add packages, and check members into tables."
    )
    staff_header_end = html.index("{message &&", staff_header_start)
    staff_header = html[staff_header_start:staff_header_end]

    assert staff_header.index("onClick={() => search('')}") < staff_header.index(
        "['staff', 'Staff Dashboard']"
    )
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_frontend_ux_safety.py::test_membership_staff_header_places_refresh_before_mode_switcher -v`

Expected: FAIL because the switcher is currently rendered before `onClick={() => search('')}` in the staff header.

- [ ] **Step 3: Write the minimal implementation**

In the existing staff Membership header action container, move the unchanged Refresh button before the existing switcher `<div>`. The resulting child order must be:

```jsx
<button onClick={() => search('')} style={{background:'#fff',border:'1px solid #E8E6E1',borderRadius:8,padding:'10px 14px',fontWeight:800,fontFamily:'inherit',cursor:'pointer'}}>
  {loading ? 'Loading' : 'Refresh'}
</button>
<div style={{display:'flex',gap:8,background:'#fff',border:'1px solid #E8E6E1',borderRadius:8,padding:4}}>
  {[
    ['staff', 'Staff Dashboard'],
    ['member', 'Member Portal'],
  ].map(([id, label]) => (
    <button key={id} onClick={() => setMembershipMode(id)} style={{background:membershipMode===id?T.accentRed:'transparent',color:membershipMode===id?'#fff':'#555',border:'none',borderRadius:6,padding:'9px 12px',fontWeight:800,fontFamily:'inherit',cursor:'pointer'}}>
      {label}
    </button>
  ))}
</div>
```

- [ ] **Step 4: Run focused and regression tests**

Run: `pytest tests/test_frontend_ux_safety.py -v`

Expected: PASS, including the new ordering test and all existing frontend UX safety assertions.

Run: `docker compose build frontend`

Expected: the frontend image builds successfully.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html tests/test_frontend_ux_safety.py
git commit -m "fix: place membership refresh before switcher"
```
