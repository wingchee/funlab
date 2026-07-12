from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "index.html"


def read_frontend() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_mobile_app_shell_has_navigation_drawer():
    html = read_frontend()

    assert "function MobileNavDrawer" in html
    assert 'className="app-content"' in html
    assert 'className="mobile-menu-button"' in html
    assert "mobile-drawer-overlay" in html
    assert "mobile-nav-drawer" in html
    assert "mobile-drawer-panel" in html
    assert "mobile-drawer-open" in html
    assert "setMobileMenuOpen(false)" in html
    assert "function MobileBottomNav" not in html
    assert "<MobileBottomNav page={page} setPage={setPage}/>" not in html
    assert "@media (max-width: 720px)" in html


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
