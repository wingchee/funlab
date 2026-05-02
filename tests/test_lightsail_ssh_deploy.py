import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_lightsail_ubuntu.sh"
GUIDE = ROOT / "LIGHTSAIL_SSH_DEPLOY.md"


def test_lightsail_ssh_deploy_script_is_present_valid_bash_and_executable():
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


def test_lightsail_ssh_deploy_script_supports_clone_update_env_and_verify():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "REPO_URL" in script
    assert "git clone" in script
    assert "git pull --ff-only" in script
    assert "apt-get install" in script
    assert "docker compose" in script
    assert "SECRET_KEY" in script
    assert "OPENAI_API_KEY" in script
    assert "COMPOSE_PROJECT_NAME" in script
    assert "ufw allow" in script
    assert "/var/log/pixelcraft-lightsail-deploy.log" in script
    assert "http://127.0.0.1" in script


def test_lightsail_ssh_guide_documents_one_command_and_private_repo_path():
    guide = GUIDE.read_text(encoding="utf-8")

    assert "ssh ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP" in guide
    assert "deploy_lightsail_ubuntu.sh" in guide
    assert "REPO_URL=" in guide
    assert "private repo" in guide.lower()
    assert "/var/log/pixelcraft-lightsail-deploy.log" in guide
    assert "Networking" in guide
    assert "80/tcp" in guide
