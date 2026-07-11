from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "index.html"


def read_frontend() -> str:
    return FRONTEND.read_text(encoding="utf-8")


def test_profile_avatar_opens_an_explicit_account_menu():
    html = read_frontend()

    assert 'aria-label="Open account menu"' in html
    assert 'aria-haspopup="menu"' in html
    assert 'role="menu"' in html
    assert "Sign out" in html
    assert "click to logout" not in html.lower()


def test_app_has_non_blocking_action_notifications():
    html = read_frontend()

    assert "function AppNotification" in html
    assert 'aria-live="polite"' in html
    assert "notify(`Signed in as ${userData.name}.`, 'success')" in html
    assert "notify('Signed out.', 'success')" in html
    assert "notify('Unable to update favorites. Please try again.', 'error')" in html
    assert "notify('Pattern deleted.', 'success')" in html


def test_blocking_alerts_are_replaced_with_in_app_feedback():
    html = read_frontend()

    assert "alert(" not in html
    assert "notify('Please allow pop-ups to open the fullscreen grid.', 'error')" in html
    assert "notify('Please allow pop-ups to generate the PDF.', 'error')" in html


def test_destructive_progress_reset_requires_confirmation():
    html = read_frontend()

    assert "window.confirm('Reset all progress for this pattern?')" in html


def test_dialogs_and_keyboard_focus_have_accessible_cues():
    html = read_frontend()

    assert ":focus-visible" in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-label="Close sign in"' in html


def test_clickable_cards_and_upload_controls_are_keyboard_accessible():
    html = read_frontend()

    assert 'aria-label={isFaved ? `Remove ${pattern.title} from saved patterns` : `Save ${pattern.title}`}' in html
    assert "if(!isLoggedIn) return" not in html
    assert 'role="button"' in html
    assert 'role="checkbox"' in html
    assert 'role="radio"' in html
    assert 'aria-label="Remove selected upload"' in html


def test_member_sign_in_dialog_supports_complete_registration():
    html = read_frontend()

    assert "function LoginModal({ onClose, onLogin })" in html
    assert "const [mode, setMode] = useState('login')" in html
    assert "passwordConfirmation" in html
    assert "Confirm password" in html
    assert "Passwords do not match" in html
    assert "Create Membership" in html


def test_site_uses_one_account_auth_surface_and_browser_session():
    html = read_frontend()

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


def test_logout_and_membership_portal_share_the_global_account():
    html = read_frontend()

    assert "function clearAccountSession()" in html
    assert "localStorage.removeItem('pc_token')" in html
    assert "localStorage.removeItem('pc_user')" in html
    assert "function MembershipPage({ user, onLogout })" in html
    assert "function MemberPortalPage({ user, embedded = false, onLogout } = {})" in html
    assert "<MemberPortalPage user={user} onLogout={onLogout}" in html
    assert "<Navbar" in html and "user={user}" in html


def test_admin_and_membership_capabilities_are_independent():
    html = read_frontend()

    assert "const isAdmin = !!user?.is_admin" in html
    assert "const hasMembership = !!user?.member_code" in html
    assert "if (!hasMembership)" in html
    assert "if (!user)" in html
