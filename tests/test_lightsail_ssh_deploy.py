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


def test_lightsail_redeploy_downloads_fresh_script_for_requested_branch():
    guide = GUIDE.read_text(encoding="utf-8")
    redeploy = guide.split("## 5. Redeploy After Code Changes", 1)[1].split(
        "## 6. Troubleshooting", 1
    )[0]

    assert 'REPO_BRANCH="${REPO_BRANCH}"' in redeploy
    assert "raw.githubusercontent.com" in redeploy
    assert "${REPO_BRANCH}/scripts/deploy_lightsail_ubuntu.sh" in redeploy
    assert "| sudo" in redeploy and "bash" in redeploy
    assert "sudo /opt/pixelcraft/scripts/deploy_lightsail_ubuntu.sh" not in redeploy


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


def test_production_scripts_quiesce_writes_through_backend_health_verification():
    for script_path in (SCRIPT, DIGITALOCEAN_SCRIPT):
        script = script_path.read_text(encoding="utf-8")
        main = script.split("main() {", 1)[1]

        assert "quiesce_writes()" in script
        assert "recover_quiesced_services()" in script
        assert 'compose stop frontend backend' in script
        assert main.index("quiesce_writes") < main.index("backup_database")
        assert main.index("backup_database") < main.index("deploy_stack")
        assert main.index("deploy_stack") < main.index("verify_backend")
        assert main.index("verify_backend") < main.index("resume_public_stack")
        assert "trap 'recover_quiesced_services $?" in main
        assert "trap 'recover_quiesced_services $?' EXIT" in main


@pytest.mark.parametrize("script_path", (SCRIPT, DIGITALOCEAN_SCRIPT))
def test_quiesce_failure_restarts_prior_services_when_replacement_has_not_started(
    tmp_path, script_path
):
    harness = tmp_path / "quiesce-harness.sh"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -Eeuo pipefail
            source {str(script_path)!r}
            calls=""
            log() {{ :; }}
            compose() {{
              calls="${{calls}}|$*"
              if [[ "$*" == "ps --status running -q backend" ]]; then printf backend-id; fi
              if [[ "$*" == "ps --status running -q frontend" ]]; then printf frontend-id; fi
            }}

            quiesce_writes
            [[ "${{calls}}" == *"stop frontend backend"* ]]
            recover_quiesced_services 23 || status=$?
            [[ "${{status}}" == 23 ]]
            [[ "${{calls}}" == *"start backend"* ]]
            [[ "${{calls}}" == *"start frontend"* ]]

            calls=""
            quiesce_writes
            BACKEND_REPLACEMENT_STARTED=true
            recover_quiesced_services 24 || status=$?
            [[ "${{status}}" == 24 ]]
            [[ "${{calls}}" != *"start backend"* ]]
            [[ "${{calls}}" != *"start frontend"* ]]
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(harness)], text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script_path", (SCRIPT, DIGITALOCEAN_SCRIPT))
def test_explicit_exit_failure_also_recovers_prior_services(tmp_path, script_path):
    calls = tmp_path / "calls"
    harness = tmp_path / "exit-recovery-harness.sh"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -Eeuo pipefail
            source {str(script_path)!r}
            BACKEND_WAS_RUNNING=true
            FRONTEND_WAS_RUNNING=true
            WRITES_QUIESCED=true
            BACKEND_REPLACEMENT_STARTED=false
            log() {{ :; }}
            compose() {{ printf '%s\n' "$*" >> {str(calls)!r}; }}
            trap 'recover_quiesced_services $?' EXIT
            exit 31
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(harness)], text=True, capture_output=True, check=False
    )

    assert result.returncode == 31
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "start backend",
        "start frontend",
    ]


@pytest.mark.parametrize("script_path", (SCRIPT, DIGITALOCEAN_SCRIPT))
@pytest.mark.parametrize("failure_phase", ("build", "partial_stop"))
def test_pre_replacement_failure_restores_services_and_pinned_checkpoint(
    tmp_path, script_path, failure_phase
):
    calls = tmp_path / "calls"
    harness = tmp_path / "pre-replacement-failure.sh"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -Eeuo pipefail
            source {str(script_path)!r}
            APP_DIR={str(tmp_path)!r}
            ENV_FILE="${{APP_DIR}}/.env"
            failure_phase={failure_phase!r}
            sudo_cmd() {{ "$@"; }}
            log() {{ :; }}
            revision=old-running-commit
            current_git_revision() {{ printf '%s\n' "${{revision}}"; }}
            compose() {{
              printf '%s\n' "$*" >> {str(calls)!r}
              case "$*" in
                "ps --status running -q backend") printf backend-id ;;
                "ps --status running -q frontend") printf frontend-id ;;
                "stop frontend backend")
                  [[ "${{failure_phase}}" == partial_stop ]] && return 41
                  ;;
                "build backend")
                  [[ "${{failure_phase}}" == build ]] && return 42
                  ;;
              esac
            }}

            write_checkpoint_value "${{APP_DIR}}/.previous-deploy-commit" old-running-commit
            write_checkpoint_value "${{APP_DIR}}/.rollback-backup" /backups/original.db
            touch "${{APP_DIR}}/.deploy-in-progress"
            revision=failed-new-commit
            begin_deployment_checkpoint
            persist_rollback_backup_once /backups/retry-diagnostic.db
            trap 'recover_quiesced_services $?' ERR
            trap 'recover_quiesced_services $?' EXIT
            quiesce_writes
            deploy_stack
            trap - ERR EXIT
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(harness)], text=True, capture_output=True, check=False
    )

    assert result.returncode != 0
    recorded_calls = calls.read_text(encoding="utf-8").splitlines()
    assert "start backend" in recorded_calls
    assert "start frontend" in recorded_calls
    assert (tmp_path / ".previous-deploy-commit").read_text().strip() == "old-running-commit"
    assert (tmp_path / ".rollback-backup").read_text().strip() == "/backups/original.db"


def test_backend_build_completes_before_replacement_is_marked():
    for script_path in (SCRIPT, DIGITALOCEAN_SCRIPT):
        deploy = script_path.read_text(encoding="utf-8").split(
            "deploy_stack() {", 1
        )[1].split("verify_backend()", 1)[0]
        assert deploy.index("compose build backend") < deploy.index(
            "BACKEND_REPLACEMENT_STARTED=true"
        ) < deploy.index("compose up -d backend")


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


def test_lightsail_pull_reexecs_checked_out_script_once_with_preserved_environment():
    script = SCRIPT.read_text(encoding="utf-8")
    update_path = script.split('if [[ -f "${APP_DIR}/docker-compose.yml" ]]', 1)[1]
    reexec = script.split("reexec_with_fresh_script() {", 1)[1].split(
        "fetch_or_update_project()", 1
    )[0]

    assert update_path.index("git pull --ff-only") < update_path.index(
        "reexec_with_fresh_script"
    )
    assert 'PIXELCRAFT_REEXECUTED:-false' in reexec
    assert 'PIXELCRAFT_REEXECUTED=true' in reexec
    assert '${APP_DIR}/scripts/deploy_lightsail_ubuntu.sh' in reexec
    for variable in (
        "REPO_URL",
        "REPO_BRANCH",
        "APP_DIR",
        "ENV_FILE",
        "PORT",
        "COMPOSE_PROJECT_NAME",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_IMAGE_MODEL",
        "OPENAI_GRID_MODEL",
    ):
        assert f'"{variable}=' in reexec
    assert '-z "${BASH_SOURCE[0]:-}"' in script


def test_lightsail_reexec_guard_prevents_loop_and_preserves_checkpoint(tmp_path):
    harness = tmp_path / "reexec-harness.sh"
    fresh_script = tmp_path / "scripts" / "deploy_lightsail_ubuntu.sh"
    fresh_script.parent.mkdir()
    fresh_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -Eeuo pipefail
            source {str(SCRIPT)!r}
            APP_DIR={str(tmp_path)!r}
            REPO_URL=https://example.test/repo.git
            REPO_BRANCH=release-candidate
            ENV_FILE="${{APP_DIR}}/.env"
            PORT=8080
            COMPOSE_PROJECT_NAME=pixelcraft-test
            OPENAI_API_KEY=test-key
            sudo_cmd() {{ "$@"; }}
            log() {{ :; }}
            exec_count=0
            exec() {{
              exec_count=$((exec_count + 1))
              exec_args="$*"
              return 0
            }}
            revision=old-running-commit
            current_git_revision() {{ printf '%s\\n' "${{revision}}"; }}

            begin_deployment_checkpoint
            persist_rollback_backup_once /backups/original.db
            reexec_with_fresh_script
            [[ "${{exec_count}}" == 1 ]]
            [[ "${{exec_args}}" == *"PIXELCRAFT_REEXECUTED=true"* ]]
            [[ "${{exec_args}}" == *"REPO_BRANCH=release-candidate"* ]]
            [[ "${{exec_args}}" == *"${{APP_DIR}}/scripts/deploy_lightsail_ubuntu.sh"* ]]

            PIXELCRAFT_REEXECUTED=true
            reexec_with_fresh_script
            begin_deployment_checkpoint
            [[ "${{exec_count}}" == 1 ]]
            [[ "$(<"${{APP_DIR}}/.previous-deploy-commit")" == old-running-commit ]]
            [[ "$(<"${{APP_DIR}}/.rollback-backup")" == /backups/original.db ]]
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(harness)], text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr


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
