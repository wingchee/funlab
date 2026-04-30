import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_digitalocean_ubuntu.sh"


def test_digitalocean_deploy_script_is_present_and_valid_bash():
    assert SCRIPT.exists()

    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_digitalocean_deploy_script_has_required_operations():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "apt-get install" in script
    assert "docker compose" in script
    assert "SECRET_KEY" in script
    assert "COMPOSE_PROJECT_NAME" in script
    assert "ufw allow" in script
    assert "curl -fsS" in script
    assert "http://127.0.0.1" in script


def test_digitalocean_deploy_script_is_executable():
    mode = SCRIPT.stat().st_mode

    assert mode & os.X_OK
