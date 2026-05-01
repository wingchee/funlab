# Lightsail SSH Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the easiest deployment path for an already-created Ubuntu AWS Lightsail instance.

**Architecture:** Create a root-safe Bash deploy script that installs host dependencies, clones or updates the repo in `/opt/pixelcraft`, prepares `.env`, starts the existing Docker Compose stack, and verifies the app locally. Add a short SSH-focused guide with one-command public-repo usage and a safer private-repo path.

**Tech Stack:** Bash, Docker Compose, Ubuntu apt, pytest static checks.

---

### Task 1: Add Static Tests

**Files:**
- Create: `tests/test_lightsail_ssh_deploy.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lightsail_ssh_deploy.py -q`

Expected: FAIL because `scripts/deploy_lightsail_ubuntu.sh` and `LIGHTSAIL_SSH_DEPLOY.md` do not exist.

### Task 2: Add Deploy Script

**Files:**
- Create: `scripts/deploy_lightsail_ubuntu.sh`

- [ ] **Step 1: Implement the script**

Create a Bash script based on `scripts/deploy_digitalocean_ubuntu.sh`, with these Lightsail-specific differences:

```bash
REPO_URL="${REPO_URL:-https://github.com/wingchee/funlab.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/pixelcraft}"
LOG_FILE="${LOG_FILE:-/var/log/pixelcraft-lightsail-deploy.log}"
```

The script must:
- Install base packages and Docker if needed.
- Clone the repo if `${APP_DIR}/docker-compose.yml` does not exist.
- Run `git fetch origin "${REPO_BRANCH}"` and `git pull --ff-only origin "${REPO_BRANCH}"` when the repo already exists.
- Generate `SECRET_KEY` only when missing or set to the default placeholder.
- Preserve existing `.env` values, including `OPENAI_API_KEY`.
- Start the Compose stack and verify `/api/patterns`.

- [ ] **Step 2: Mark it executable**

Run: `chmod +x scripts/deploy_lightsail_ubuntu.sh`

### Task 3: Add SSH Deploy Guide

**Files:**
- Create: `LIGHTSAIL_SSH_DEPLOY.md`
- Modify: `DEPLOYMENT.md`

- [ ] **Step 1: Write the guide**

Document:
- Lightsail Ubuntu instance requirements.
- Networking tab rules for `22/tcp` and `80/tcp`.
- Public repo one-command deploy using `curl ... | sudo REPO_URL=... bash`.
- Private repo clone-then-run deploy.
- Redeploy command.
- Logs and troubleshooting commands.

- [ ] **Step 2: Link the guide from the main deployment guide**

Add `LIGHTSAIL_SSH_DEPLOY.md` beside the existing Lightsail launch-script guide.

### Task 4: Verify

**Files:**
- Test: `tests/test_lightsail_ssh_deploy.py`
- Test: `tests/test_lightsail_launch.py`
- Test: `tests/test_digitalocean_deploy.py`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_lightsail_ssh_deploy.py tests/test_lightsail_launch.py tests/test_digitalocean_deploy.py -q`

Expected: all tests pass.
