from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_runs_bead_editor_as_separate_service():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "bead-editor:" in compose
    assert "context: ./perler-beads-master" in compose
    assert "bead-editor" in compose.split("frontend:", 1)[1]


def test_nginx_routes_bead_editor_without_replacing_pixelcraft():
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "location = /bead-editor/" in nginx
    assert "location /bead-editor" in nginx
    assert "return 308 /bead-editor/" not in nginx
    assert "proxy_pass         http://bead-editor:3000" in nginx
    assert "location /api/" in nginx


def test_admin_preview_opens_editor_in_same_window_and_restores_result():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "Edit Grid" in html
    assert "pixelcraft_admin_draft" in html
    assert "pixelcraft_editor_payload" in html
    assert "pixelcraft_editor_result" in html
    assert "source_image_data_url" in html
    assert "window.open('/bead-editor?pixelcraft=1'" not in html
    assert "window.location.href = '/bead-editor?pixelcraft=1" in html
    assert "restorePixelCraftDraft" in html


def test_admin_preview_ai_enhance_posts_image_and_current_grid_json():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    page = (ROOT / "perler-beads-master" / "src" / "app" / "page.tsx").read_text(
        encoding="utf-8"
    )
    admin = (ROOT / "backend" / "routers" / "admin.py").read_text(encoding="utf-8")
    openai_grid = (ROOT / "backend" / "openai_grid.py").read_text(encoding="utf-8")

    assert "AI Enhance" in html
    assert "handleAiEnhancePreview" in html
    assert "current_grid_json" in html
    assert "form.append('current_grid_json', JSON.stringify(activeResult));" in html
    assert "handleAiEnhanceFromEditor" not in page
    assert "current_grid_json: Optional[str] = Form(None)" in admin
    assert 'grid_kwargs["current_grid_json"] = current_grid_json' in admin
    assert "current_grid_json" in openai_grid


def test_admin_ai_enhancement_is_paused_without_removing_endpoint():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    admin = (ROOT / "backend" / "routers" / "admin.py").read_text(encoding="utf-8")

    assert "const AI_ENHANCEMENT_ENABLED = false" in html
    assert "if (!AI_ENHANCEMENT_ENABLED) return;" in html
    assert '@router.post("/enhance-preview")' in admin


def test_mard_221_palette_is_enforced_in_portal_and_editor():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    editor_page = (ROOT / "perler-beads-master" / "src" / "app" / "page.tsx").read_text(
        encoding="utf-8"
    )
    editor_utils = (
        ROOT / "perler-beads-master" / "src" / "utils" / "colorSystemUtils.ts"
    ).read_text(encoding="utf-8")
    floating_palette = (
        ROOT / "perler-beads-master" / "src" / "components" / "FloatingColorPalette.tsx"
    ).read_text(encoding="utf-8")
    backend_mapping = (ROOT / "backend" / "color_system_mapping.json").read_text(
        encoding="utf-8"
    )
    editor_mapping = (
        ROOT / "perler-beads-master" / "src" / "app" / "colorSystemMapping.json"
    ).read_text(encoding="utf-8")

    assert "MARD 221" in html
    assert "MARD 221" in editor_page
    assert "MARD 221" in floating_palette
    assert "colorSystemOptions.map" not in editor_page
    assert "完整色板 (291)" not in floating_palette
    assert "COCO" not in editor_utils
    assert "漫漫" not in editor_utils
    assert backend_mapping == editor_mapping


def test_stale_admin_page_state_falls_back_to_gallery_for_non_admins():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "if (!authLoading && page === 'admin' && !user?.is_admin) setPage('gallery');" in html
    assert "}, [authLoading, page, user?.is_admin]);" in html


def test_admin_upload_input_can_reselect_same_image():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "const resetFileInput = () =>" in html
    assert "accept=\"image/png,image/jpeg,image/webp,.csv,text/csv\"" in html
    assert "handleFileSelect(e.target.files?.[0]);" in html
    assert "e.target.value = '';" in html
    assert "resetFileInput(); fileInputRef.current?.click();" in html
    assert "Image must be 20 MB or smaller" in html
    assert "CSV must be 5 MB or smaller" in html
    assert "Import CSV Pattern" in html


def test_editor_is_embeddable_under_bead_editor_base_path():
    page = (ROOT / "perler-beads-master" / "src" / "app" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "perlerbeadsold.zippland.com" not in page
    assert "window.location.href = '/bead-editor/focus'" in page
    assert "Done" in page
    assert "PixelCraft Edit Mode" not in page
    assert "window.location.href = returnUrl" in page
    assert "showPixelCraftWorkspace" in page


def test_pixelcraft_editor_keeps_imported_grid_without_repixelating():
    page = (ROOT / "perler-beads-master" / "src" / "app" / "page.tsx").read_text(
        encoding="utf-8"
    )

    assert "applyPixelCraftResult(payload.result);" in page
    assert "if (isPixelCraftMode) return;" in page
    assert "remapTrigger, isPixelCraftMode]" in page


def test_pixelcraft_editor_uses_full_page_clean_workspace():
    page = (ROOT / "perler-beads-master" / "src" / "app" / "page.tsx").read_text(
        encoding="utf-8"
    )
    canvas = (
        ROOT / "perler-beads-master" / "src" / "components" / "PixelatedPreviewCanvas.tsx"
    ).read_text(encoding="utf-8")
    toolbar = (
        ROOT / "perler-beads-master" / "src" / "components" / "FloatingToolbar.tsx"
    ).read_text(encoding="utf-8")

    assert "{!isPixelCraftMode && <InstallPWA />}" in page
    assert "setIsFloatingPaletteOpen(false);" in page
    assert "h-screen overflow-hidden p-0" in page
    assert "fitToViewport={showPixelCraftWorkspace}" in page
    assert "{!isPixelCraftMode && <footer" in page
    assert "showExitManualMode={!isPixelCraftMode}" in page
    assert "fitToViewport?: boolean;" in canvas
    assert "window.addEventListener('resize', resizeCanvas);" in canvas
    assert "showExitManualMode = true" in toolbar
