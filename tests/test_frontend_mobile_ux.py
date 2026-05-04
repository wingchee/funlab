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
