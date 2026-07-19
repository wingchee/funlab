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


def test_member_sign_in_dialog_is_sign_in_only():
    html = read_frontend()

    assert "function LoginModal({ onClose, onLogin })" in html
    assert "apiFetch('/auth/register'" not in html
    assert "Create Membership" not in html
    assert "sign in or create an account" not in html.lower()


def test_site_uses_one_account_auth_surface_and_browser_session():
    html = read_frontend()

    assert "apiFetch('/auth/login'" in html
    assert "apiFetch('/auth/register'" not in html
    assert "'/members/login'" not in html
    assert "'/members/register'" not in html
    assert "pc_member_token" not in html
    assert "pc_token_type" not in html
    assert "memberApiFetch" not in html
    assert "localStorage.setItem('pc_token', token)" in html
    assert "localStorage.setItem('pc_user', JSON.stringify(account))" in html
    assert "member_code" in html
    assert "Membership profile required" in html


def test_staff_can_create_members_and_manage_public_balance_links():
    html = read_frontend()

    assert "function AddMemberPage" in html
    assert "apiFetch('/members'" in html
    assert "balance-qr?origin=" in html


def test_public_member_balance_route_uses_an_unauthenticated_token_lookup():
    html = read_frontend()

    assert "function PublicMemberBalancePage" in html
    assert "apiFetch(`/members/public/${token}`)" in html
    assert "window.location.pathname.startsWith('/member/')" in html


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


def test_staff_ui_can_promote_and_safely_remove_membership_capability():
    html = read_frontend()

    assert "Promote to Member" in html
    assert "Remove Membership" in html
    assert "method:'POST'" in html and "`/members/${selected.id}/membership`" in html
    assert "method:'DELETE'" in html
    assert 'placeholder="Name, phone, or Member ID"' in html


def test_staff_ui_can_add_and_edit_manual_member_check_in_history():
    html = read_frontend()
    membership_source = html[
        html.index("function MembershipPage({ user, onLogout })"):
        html.index("function MemberPortalPage(")
    ]

    assert "Add Check-in Record" in membership_source
    assert "Edit Check-in Record" in membership_source
    assert "`/members/${selected.id}/visits`" in membership_source
    assert "`/members/${selected.id}/visits/${editingVisit.id}`" in membership_source


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


def test_member_portal_ignores_stale_account_responses():
    html = read_frontend()

    assert "const memberLoadGenerationRef = useRef(0)" in html
    assert "const currentAccountIdRef = useRef(user?.id)" in html
    assert "currentAccountIdRef.current = user?.id" in html
    assert "memberLoadGenerationRef.current === generation" in html
    assert "currentAccountIdRef.current === accountId" in html
    assert "const generation = ++memberLoadGenerationRef.current" in html
    assert "memberLoadGenerationRef.current += 1" in html
    assert "const logout = () =>" in html
    assert html.count("if (!isCurrentLoad()) return") >= 5


def test_member_portal_revokes_latest_qr_url_on_unmount():
    html = read_frontend()

    assert "const qrUrlRef = useRef('')" in html
    assert "qrUrlRef.current = nextUrl" in html
    assert "return () => {" in html
    assert "URL.revokeObjectURL(qrUrlRef.current)" in html
    assert "qrUrlRef.current = ''" in html


def test_membership_staff_header_keeps_refresh_control():
    html = read_frontend()
    staff_header_start = html.index(
        "Search members, scan QR codes, add packages, and check members into tables."
    )
    staff_header_end = html.index("{message &&", staff_header_start)
    staff_header = html[staff_header_start:staff_header_end]

    assert "onClick={() => search('')}" in staff_header
    assert "Refresh" in staff_header


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


def test_dedicated_phone_inputs_use_an_australian_example():
    html = read_frontend()

    assert html.count('placeholder="+61 412 345 678" type="tel"') == 3
    assert 'id="new-member-phone"' in html
    assert 'placeholder="+60 12-345 6789"' not in html
