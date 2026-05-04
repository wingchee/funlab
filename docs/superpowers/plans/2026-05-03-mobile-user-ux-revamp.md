# Mobile User UX Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PixelCraft/FunLab AU more comfortable on mobile for public/member users while keeping admin optimized for tablet and desktop.

**Architecture:** Keep the current single-file React app in `frontend/index.html`. Add responsive CSS classes and small React composition helpers instead of migrating frameworks or changing backend contracts. Add static frontend regression tests that assert the mobile shell, bead viewer, and admin responsive hooks exist.

**Tech Stack:** Static HTML, React 18 UMD, Babel standalone, CSS media queries, pytest for file-level frontend regression tests.

---

## File Structure

- Modify: `frontend/index.html`
  - Add responsive CSS utilities, mobile bottom navigation, mobile page spacing, mobile-friendly pattern cards, bead-map sheet classes, and admin/tablet responsive hooks.
  - Preserve existing API calls, auth state, localStorage keys, and React component names.
- Create: `tests/test_frontend_mobile_ux.py`
  - Static regression tests for the responsive UI structure.
- Existing ignored directories:
  - Do not modify `BeanBuddy-AI-main/`.
  - Do not modify `perler-beads-master/`.

## Task 1: Add Frontend Responsive Regression Tests

**Files:**
- Create: `tests/test_frontend_mobile_ux.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_frontend_mobile_ux.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "index.html"


def read_frontend() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_mobile_app_shell_has_bottom_navigation_and_content_offset():
    html = read_frontend()

    assert "function MobileBottomNav" in html
    assert 'className="app-content"' in html
    assert 'className="mobile-bottom-nav"' in html
    assert "@media (max-width: 720px)" in html
    assert "padding-bottom: calc(74px + env(safe-area-inset-bottom))" in html


def test_gallery_and_cards_have_mobile_comfort_classes():
    html = read_frontend()

    assert 'className="page-shell gallery-page pixel-bg"' in html
    assert 'className="page-header"' in html
    assert 'className="library-toolbar"' in html
    assert 'className="pattern-grid"' in html
    assert 'className="pattern-card"' in html
    assert 'className="filter-chips"' in html


def test_bead_viewer_has_mobile_sheet_and_sticky_actions():
    html = read_frontend()

    assert 'className="viewer-overlay"' in html
    assert 'className="viewer-modal scale-in"' in html
    assert 'className="viewer-header"' in html
    assert 'className="viewer-body"' in html
    assert 'className="viewer-actions"' in html
    assert 'className="viewer-legend"' in html


def test_admin_keeps_tablet_desktop_layout_with_mobile_safe_fallbacks():
    html = read_frontend()

    assert 'className="admin-layout"' in html
    assert 'className="admin-action-row"' in html
    assert ".admin-layout" in html
    assert ".admin-action-row" in html
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/test_frontend_mobile_ux.py -q
```

Expected: FAIL because `MobileBottomNav`, `app-content`, `pattern-card`, viewer classes, and admin responsive classes do not exist yet.

## Task 2: Add Responsive CSS System

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add CSS classes before the first existing media query**

Add a responsive class layer in the `<style>` block:

```css
.app-content { min-height: calc(100vh - 60px); }
.mobile-bottom-nav { display: none; }
.page-shell { min-height: calc(100vh - 60px); padding: 40px; }
.page-inner { max-width: 1180px; margin: 0 auto; }
.page-header { margin-bottom: 28px; }
.library-toolbar { display: flex; gap: 12px; margin-bottom: 28px; flex-wrap: wrap; align-items: center; }
.filter-chips { display: flex; gap: 6px; }
.pattern-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 20px; }
.pattern-card { background: #fff; border-radius: 8px; overflow: hidden; cursor: pointer; }
.viewer-overlay { position: fixed; inset: 0; background: rgba(26,26,24,0.7); backdrop-filter: blur(6px); z-index: 200; display: flex; align-items: center; justify-content: center; padding: 20px; }
.viewer-modal { background: #fff; border-radius: 20px; width: min(920px, 95vw); max-height: 90vh; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 24px 80px rgba(0,0,0,0.25); }
.viewer-header { padding: 18px 24px; border-bottom: 1px solid #f0ede8; display: flex; align-items: center; gap: 16px; }
.viewer-body { display: flex; flex: 1; overflow: hidden; min-height: 0; }
.viewer-grid-area { flex: 1; overflow: auto; padding: 24px; }
.viewer-legend { width: 200px; border-left: 1px solid #f0ede8; padding: 20px 16px; overflow: auto; flex-shrink: 0; }
.viewer-actions { display: grid; gap: 8px; margin-top: 16px; }
.admin-layout { display: grid; grid-template-columns: 1fr 380px; gap: 24px; max-width: 960px; }
.admin-action-row { display: flex; gap: 10px; flex-wrap: wrap; }

@media (max-width: 720px) {
  .desktop-nav-links { display: none !important; }
  .app-content { padding-bottom: calc(74px + env(safe-area-inset-bottom)); }
  .mobile-bottom-nav {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 140;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
    background: rgba(255,255,255,0.96);
    border-top: 1px solid #E8E6E1;
    backdrop-filter: blur(14px);
  }
  .page-shell { padding: 24px 16px; }
  .page-header h1 { font-size: 30px !important; line-height: 1.02 !important; }
  .library-toolbar { gap: 10px; margin-bottom: 20px; }
  .library-toolbar > * { width: 100%; max-width: none !important; }
  .filter-chips { overflow-x: auto; padding-bottom: 4px; margin-inline: -16px; padding-inline: 16px; }
  .filter-chips button { flex: 0 0 auto; min-height: 40px; }
  .pattern-grid { grid-template-columns: 1fr; gap: 14px; }
  .pattern-card { display: grid; grid-template-columns: 128px 1fr; min-height: 150px; }
  .viewer-overlay { align-items: stretch; padding: 0; }
  .viewer-modal { width: 100vw; max-height: none; height: 100dvh; border-radius: 0; }
  .viewer-header { position: sticky; top: 0; z-index: 2; background: #fff; flex-wrap: wrap; padding: 14px 16px; }
  .viewer-body { display: block; overflow: auto; background: #f8f7f4; }
  .viewer-grid-area { padding: 14px 14px 96px; overflow: auto; }
  .viewer-legend { width: auto; border-left: 0; border-top: 1px solid #f0ede8; background: #fff; }
  .viewer-actions { position: sticky; bottom: 0; background: #fff; padding-top: 8px; }
  .admin-layout { grid-template-columns: 1fr; max-width: none; }
  .admin-action-row > button { min-width: 140px; }
}
```

- [ ] **Step 2: Run the tests**

Run:

```bash
pytest tests/test_frontend_mobile_ux.py -q
```

Expected: Still FAIL because React markup has not been wired to the new classes.

## Task 3: Wire Mobile App Shell And User Pages

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add `MobileBottomNav` after `Navbar`**

Add:

```jsx
function MobileBottomNav({ page, setPage }) {
  const items = [
    ['home', 'Home', '⌂'],
    ['gallery', 'Library', '▦'],
    ['favorites', 'Saved', '♡'],
    ['timetable', 'Time', '◷'],
  ];
  return (
    <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
      {items.map(([id, label, icon]) => (
        <button key={id} onClick={() => setPage(id)} className={page === id ? 'active' : ''}>
          <span aria-hidden="true">{icon}</span>
          <strong>{label}</strong>
        </button>
      ))}
    </nav>
  );
}
```

- [ ] **Step 2: Add `desktop-nav-links` to the desktop nav links container**

Change the nav links wrapper to:

```jsx
<div className="desktop-nav-links" style={{display:'flex',gap:4,flex:1}}>
```

- [ ] **Step 3: Wrap page content and render bottom nav in `App`**

Change:

```jsx
<Navbar page={page} setPage={setPage} user={user} onLoginClick={() => setShowLogin(true)} onLogout={onLogout}/>
```

to:

```jsx
<Navbar page={page} setPage={setPage} user={user} onLoginClick={() => setShowLogin(true)} onLogout={onLogout}/>
<MobileBottomNav page={page} setPage={setPage}/>
<main className="app-content">
```

Close the `main` after the page branches and before modals.

- [ ] **Step 4: Add page classes**

Update root wrappers:

```jsx
<div className="page-shell gallery-page pixel-bg">
<div className="page-inner">
```

Use the same `page-shell pixel-bg` and `page-inner` pattern for Favorites and Time Table.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_frontend_mobile_ux.py -q
```

Expected: Gallery/card/viewer/admin tests still fail until the next tasks.

## Task 4: Wire Gallery Cards, Filters, Viewer, And Admin Classes

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add `pattern-card` to `PatternCard` root**

Change the root card opening to include:

```jsx
className="pattern-card"
```

- [ ] **Step 2: Add `page-header`, `library-toolbar`, `filter-chips`, and `pattern-grid`**

Apply these classes to Gallery and Favorites wrappers:

```jsx
<div className="page-header" style={{marginBottom:32}}>
<div className="library-toolbar" style={{display:'flex',gap:12,marginBottom:32,flexWrap:'wrap',alignItems:'center'}}>
<div className="filter-chips" style={{display:'flex',gap:6}}>
<div className="pattern-grid" style={{display:'grid',gridTemplateColumns:'repeat(auto-fill, minmax(240px, 1fr))',gap:20}}>
```

- [ ] **Step 3: Add viewer classes**

Change viewer structural wrappers:

```jsx
<div className="viewer-overlay" ...>
<div className="viewer-modal scale-in" ...>
<div className="viewer-header" ...>
<div className="viewer-body" ...>
<div className="viewer-grid-area" ...>
<div className="viewer-legend" ...>
<div className="viewer-actions">
```

- [ ] **Step 4: Add admin classes**

Change admin layout and preview action row:

```jsx
<div className="admin-layout" style={{display:'grid',gridTemplateColumns:'1fr 380px',gap:24,maxWidth:960}}>
<div className="admin-action-row" style={{display:'flex',gap:10}}>
```

- [ ] **Step 5: Run tests and verify pass**

Run:

```bash
pytest tests/test_frontend_mobile_ux.py -q
```

Expected: PASS.

## Task 5: Browser Verification And Responsive Polish

**Files:**
- Modify: `frontend/index.html` only if verification finds visual issues.

- [ ] **Step 1: Serve or use the existing local app**

If `http://localhost:3000/` is running, use it. Otherwise run the project’s existing stack command if needed:

```bash
docker compose up
```

- [ ] **Step 2: Verify mobile user flows**

Use the in-app browser at a phone-sized viewport if available, or inspect the current viewport and mobile CSS:

- Home page: compact hero, no horizontal overflow, bottom nav visible.
- Library page: full-width search, scrollable filters, one-column comfortable cards.
- Saved page: logged-out and empty states are not covered by bottom nav.
- Bead map viewer: sheet layout, sticky header, grid scroll area, sticky actions.
- Login modal: does not overflow phone width.

- [ ] **Step 3: Verify desktop/tablet flows**

Check:

- Desktop top nav still works.
- Library desktop grid still behaves like before.
- Bead map desktop modal still has side legend.
- Admin keeps two-column layout on wide screens and collapses safely on narrow screens.

- [ ] **Step 4: Run focused tests again**

Run:

```bash
pytest tests/test_frontend_mobile_ux.py -q
```

Expected: PASS.

## Self-Review

- Spec coverage: app shell, home, library, saved, bead viewer, timetable, and admin responsive cleanup are covered.
- Placeholder scan: no deferred placeholders are allowed in the implementation tasks.
- Type consistency: all new identifiers are CSS classes or the `MobileBottomNav` React helper declared before `App`.
