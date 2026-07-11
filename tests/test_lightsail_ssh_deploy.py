import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_lightsail_ubuntu.sh"
DIGITALOCEAN_SCRIPT = ROOT / "scripts" / "deploy_digitalocean_ubuntu.sh"
GUIDE = ROOT / "LIGHTSAIL_SSH_DEPLOY.md"
DEPLOYMENT_GUIDES = (
    ROOT / "DEPLOYMENT.md",
    ROOT / "DIGITALOCEAN_UBUNTU_DEPLOYMENT.md",
)


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


def test_production_scripts_verify_database_backup_before_starting_migrations():
    for script_path in (SCRIPT, DIGITALOCEAN_SCRIPT):
        script = script_path.read_text(encoding="utf-8")
        main = script.split("main() {", 1)[1]

        assert "backup_database()" in script
        assert '${APP_DIR}/backups' in script
        assert "src.backup(dst)" in script
        assert 'PRAGMA integrity_check' in script
        assert "python3" in script.split("install_base_packages()", 1)[1].split("}", 1)[0]
        assert main.index("backup_database") < main.index("deploy_stack")
        assert main.index("backup_database") < main.index(
            "rotate_secret_for_unified_accounts_once"
        ) < main.index("deploy_stack")


def test_production_scripts_record_previous_commit_and_rotate_secret_only_once():
    for script_path in (SCRIPT, DIGITALOCEAN_SCRIPT):
        script = script_path.read_text(encoding="utf-8")

        assert ".previous-deploy-commit" in script
        assert "git rev-parse HEAD" in script
        assert "UNIFIED_ACCOUNT_SECRET_ROTATED" in script
        assert "Rotated SECRET_KEY once for unified account migration" in script

    lightsail = SCRIPT.read_text(encoding="utf-8")
    update_path = lightsail.split('if [[ -f "${APP_DIR}/docker-compose.yml" ]]', 1)[1]
    assert update_path.index(".previous-deploy-commit") < update_path.index("git pull --ff-only")


def test_production_guides_document_verified_backup_rotation_and_exact_restore():
    required_restore_commands = (
        'BACKUP="$(ls -1t /opt/pixelcraft/backups/pindou-*.db | head -n 1)"',
        'PREVIOUS_COMMIT="$(cat /opt/pixelcraft/.previous-deploy-commit)"',
        "sudo docker compose --project-name pixelcraft --env-file .env down",
        "sudo docker volume inspect pixelcraft_pindou_data",
        'sudo install -m 0600 "${BACKUP}" "${MOUNTPOINT}/pindou.db"',
        'sudo git checkout "${PREVIOUS_COMMIT}"',
        "sudo docker compose --project-name pixelcraft --env-file .env up --build -d",
    )

    for guide_path in DEPLOYMENT_GUIDES:
        guide = guide_path.read_text(encoding="utf-8")

        assert "/opt/pixelcraft/backups/pindou-" in guide
        assert "SECRET_KEY" in guide and "sign" in guide.lower()
        assert "docker compose down -v" in guide
        for command in required_restore_commands:
            assert command in guide
