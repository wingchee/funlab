import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lightsail_launch_ubuntu.sh"
GUIDE = ROOT / "LIGHTSAIL_UBUNTU_LAUNCH.md"


def test_lightsail_launch_script_is_present_valid_bash_and_executable():
    assert SCRIPT.exists()

    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert SCRIPT.stat().st_mode & os.X_OK


def test_lightsail_launch_script_supports_first_boot_deploy():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "REPO_URL" in script
    assert "git clone" in script
    assert "apt-get install" in script
    assert "docker compose" in script
    assert "SECRET_KEY" in script
    assert "COMPOSE_PROJECT_NAME" in script
    assert "ufw allow" in script
    assert "/var/log/pixelcraft-lightsail-launch.log" in script
    assert "tee -a" in script
    assert "http://127.0.0.1" in script


def test_lightsail_launch_guide_documents_required_placeholders():
    guide = GUIDE.read_text(encoding="utf-8")

    assert "Launch script" in guide
    assert "REPO_URL=" in guide
    assert "Networking" in guide
    assert "80" in guide
    assert "22" in guide
