import os
import subprocess
import textwrap
from pathlib import Path

import pytest


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
        assert "rev-parse HEAD" in script
        assert "UNIFIED_ACCOUNT_SECRET_ROTATED" in script
        assert "Rotated SECRET_KEY once for unified account migration" in script

    lightsail = SCRIPT.read_text(encoding="utf-8")
    update_path = lightsail.split('if [[ -f "${APP_DIR}/docker-compose.yml" ]]', 1)[1]
    assert update_path.index("begin_deployment_checkpoint") < update_path.index(
        "git pull --ff-only"
    )


def test_production_scripts_checkpoint_attempt_before_backup_and_complete_after_health():
    for script_path in (SCRIPT, DIGITALOCEAN_SCRIPT):
        script = script_path.read_text(encoding="utf-8")
        main = script.split("main() {", 1)[1]

        assert ".deploy-in-progress" in script
        assert ".rollback-backup" in script
        assert ".last-successful-deploy-commit" in script
        assert "begin_deployment_checkpoint()" in script
        assert "persist_rollback_backup_once()" in script
        assert "complete_deployment_checkpoint()" in script
        assert main.index("backup_database") < main.index("deploy_stack")
        assert main.index("verify_stack") < main.index("complete_deployment_checkpoint")
        backup = script.split("backup_database() {", 1)[1].split(
            "rotate_secret_for_unified_accounts_once()", 1
        )[0]
        assert backup.index('sudo_cmd mv "${temporary_path}" "${backup_path}"') < backup.index(
            "persist_rollback_backup_once"
        )

    digitalocean_main = DIGITALOCEAN_SCRIPT.read_text(encoding="utf-8").split(
        "main() {", 1
    )[1]
    assert digitalocean_main.index("begin_deployment_checkpoint") < digitalocean_main.index(
        "backup_database"
    )


@pytest.mark.parametrize("script_path", (SCRIPT, DIGITALOCEAN_SCRIPT))
def test_failed_deployment_retry_preserves_original_rollback_pointers(
    tmp_path, script_path
):
    harness = tmp_path / "checkpoint-harness.sh"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -Eeuo pipefail
            source {str(script_path)!r}
            APP_DIR={str(tmp_path)!r}
            sudo_cmd() {{ "$@"; }}
            log() {{ :; }}
            revision=old-running-commit
            current_git_revision() {{ printf '%s\\n' "${{revision}}"; }}

            begin_deployment_checkpoint
            persist_rollback_backup_once /backups/original.db

            revision=failed-new-commit
            begin_deployment_checkpoint
            persist_rollback_backup_once /backups/retry-diagnostic.db

            [[ "$(<"${{APP_DIR}}/.previous-deploy-commit")" == old-running-commit ]]
            [[ "$(<"${{APP_DIR}}/.rollback-backup")" == /backups/original.db ]]
            [[ -f "${{APP_DIR}}/.deploy-in-progress" ]]
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(harness)], text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_production_guides_document_verified_backup_rotation_and_exact_restore():
    required_restore_commands = (
        'BACKUP="$(sudo cat /opt/pixelcraft/.rollback-backup)"',
        'PREVIOUS_COMMIT="$(sudo cat /opt/pixelcraft/.previous-deploy-commit)"',
        "sudo docker compose --project-name pixelcraft --env-file .env down",
        "sudo docker volume inspect pixelcraft_pindou_data",
        'sudo install -m 0600 "${BACKUP}" "${MOUNTPOINT}/pindou.db"',
        'sudo git checkout "${PREVIOUS_COMMIT}"',
        "sudo docker compose --project-name pixelcraft --env-file .env up --build -d",
    )

    for guide_path in DEPLOYMENT_GUIDES:
        guide = guide_path.read_text(encoding="utf-8")

        assert "/opt/pixelcraft/backups/pindou-" in guide
        assert "newest" not in guide.lower().split("roll back a migration deployment", 1)[1]
        assert "SECRET_KEY" in guide and "sign" in guide.lower()
        assert "docker compose down -v" in guide
        rollback = guide.lower().split("roll back a migration deployment", 1)[1]
        assert rollback.index("set -e") < rollback.index("docker compose --project-name")
        for command in required_restore_commands:
            assert command in guide
