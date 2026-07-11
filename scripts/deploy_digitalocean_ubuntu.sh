#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"
PORT="${PORT:-80}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-pixelcraft}"
ENABLE_UFW="${ENABLE_UFW:-true}"
SKIP_DOCKER_INSTALL="${SKIP_DOCKER_INSTALL:-false}"

log() {
  printf '\n[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

sudo_cmd() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

compose() {
  if [[ "${EUID}" -eq 0 ]]; then
    docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${ENV_FILE}" "$@"
  else
    sudo docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${ENV_FILE}" "$@"
  fi
}

require_ubuntu() {
  [[ -r /etc/os-release ]] || fail "This script is intended for Ubuntu droplets."
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || fail "Unsupported OS '${ID:-unknown}'. Use an Ubuntu droplet."
}

require_project_files() {
  [[ -f "${APP_DIR}/docker-compose.yml" ]] || fail "Run this from the PixelCraft repo root, or set APP_DIR=/path/to/repo."
  [[ -d "${APP_DIR}/backend" ]] || fail "Missing backend directory under ${APP_DIR}."
  [[ -d "${APP_DIR}/frontend" ]] || fail "Missing frontend directory under ${APP_DIR}."
}

install_base_packages() {
  log "Installing base Ubuntu packages"
  sudo_cmd apt-get update
  sudo_cmd apt-get install -y ca-certificates curl git gnupg lsb-release openssl python3 ufw
}

install_docker() {
  if [[ "${SKIP_DOCKER_INSTALL}" == "true" ]]; then
    log "Skipping Docker installation because SKIP_DOCKER_INSTALL=true"
    return
  fi

  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker and Docker Compose plugin are already installed"
    return
  fi

  log "Installing Docker Engine and Compose plugin from Docker's Ubuntu repository"
  sudo_cmd install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /tmp/docker.asc
  sudo_cmd rm -f /etc/apt/keyrings/docker.gpg
  sudo_cmd gpg --dearmor -o /etc/apt/keyrings/docker.gpg /tmp/docker.asc
  sudo_cmd chmod a+r /etc/apt/keyrings/docker.gpg

  # shellcheck disable=SC1091
  . /etc/os-release
  local arch
  arch="$(dpkg --print-architecture)"
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' "${arch}" "${VERSION_CODENAME}" \
    | sudo_cmd tee /etc/apt/sources.list.d/docker.list >/dev/null

  sudo_cmd apt-get update
  sudo_cmd apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo_cmd systemctl enable --now docker
}

set_env_value() {
  local key="$1"
  local value="$2"

  if grep -q "^${key}=" "${ENV_FILE}"; then
    sudo_cmd sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" | sudo_cmd tee -a "${ENV_FILE}" >/dev/null
  fi
}

ensure_env_file() {
  log "Preparing ${ENV_FILE}"

  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${APP_DIR}/.env.example" ]]; then
      sudo_cmd cp "${APP_DIR}/.env.example" "${ENV_FILE}"
    else
      sudo_cmd touch "${ENV_FILE}"
    fi
  fi

  local secret
  secret="$(grep '^SECRET_KEY=' "${ENV_FILE}" | cut -d= -f2- || true)"
  if [[ -z "${secret}" || "${secret}" == "pixelcraft-change-this-in-production" ]]; then
    set_env_value "SECRET_KEY" "$(openssl rand -hex 32)"
  fi

  set_env_value "PORT" "${PORT}"
  set_env_value "COMPOSE_PROJECT_NAME" "${COMPOSE_PROJECT_NAME}"
  sudo_cmd chmod 600 "${ENV_FILE}"
}

record_previous_deploy_commit() {
  if ! sudo_cmd git -C "${APP_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "No Git checkout metadata; skipping previous deployment commit record"
    return
  fi
  local revision
  revision="$(cd "${APP_DIR}" && sudo_cmd git rev-parse HEAD)"
  printf '%s\n' "${revision}" \
    | sudo_cmd tee "${APP_DIR}/.previous-deploy-commit" >/dev/null
}

backup_database() {
  local volume_name="${COMPOSE_PROJECT_NAME}_pindou_data"
  if ! sudo_cmd docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    log "No existing database volume; skipping backup"
    return
  fi

  local mountpoint database_path backup_dir backup_path temporary_path
  mountpoint="$(sudo_cmd docker volume inspect "${volume_name}" --format '{{ .Mountpoint }}')"
  database_path="${mountpoint}/pindou.db"
  if ! sudo_cmd test -f "${database_path}"; then
    log "No existing SQLite database; skipping backup"
    return
  fi

  backup_dir="${APP_DIR}/backups"
  backup_path="${backup_dir}/pindou-$(date +'%Y%m%d-%H%M%S').db"
  temporary_path="${backup_path}.partial"
  sudo_cmd install -d -m 0700 "${backup_dir}"
  sudo_cmd rm -f "${temporary_path}"
  sudo_cmd python3 -c '
import sqlite3, sys
source, destination = sys.argv[1], sys.argv[2]
with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)
with sqlite3.connect(destination) as check:
    result = check.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    raise SystemExit(f"backup integrity check failed: {result}")
' "${database_path}" "${temporary_path}"
  sudo_cmd chmod 0600 "${temporary_path}"
  sudo_cmd mv "${temporary_path}" "${backup_path}"
  log "Verified database backup: ${backup_path}"
}

rotate_secret_for_unified_accounts_once() {
  local marker
  marker="$(grep '^UNIFIED_ACCOUNT_SECRET_ROTATED=' "${ENV_FILE}" | cut -d= -f2- || true)"
  if [[ "${marker}" == "true" ]]; then
    log "Unified-account signing-key rotation already completed"
    return
  fi
  set_env_value "SECRET_KEY" "$(openssl rand -hex 32)"
  set_env_value "UNIFIED_ACCOUNT_SECRET_ROTATED" "true"
  log "Rotated SECRET_KEY once for unified account migration"
}

configure_firewall() {
  if [[ "${ENABLE_UFW}" != "true" ]]; then
    log "Skipping UFW configuration because ENABLE_UFW is not true"
    return
  fi

  log "Configuring UFW firewall"
  sudo_cmd ufw allow OpenSSH
  sudo_cmd ufw allow "${PORT}/tcp"
  sudo_cmd ufw --force enable
}

deploy_stack() {
  log "Building and starting PixelCraft containers"
  cd "${APP_DIR}"
  compose up --build -d
}

verify_stack() {
  log "Waiting for PixelCraft to respond on http://127.0.0.1:${PORT}"

  local attempt
  for attempt in $(seq 1 30); do
    if curl -fsS --max-time 10 "http://127.0.0.1:${PORT}/api/patterns" >/dev/null; then
      log "PixelCraft is responding"
      compose ps
      return
    fi
    sleep 2
  done

  compose ps || true
  compose logs --tail=120 || true
  fail "PixelCraft did not respond on http://127.0.0.1:${PORT}/api/patterns"
}

main() {
  require_ubuntu
  require_project_files
  install_base_packages
  install_docker
  record_previous_deploy_commit
  ensure_env_file
  backup_database
  rotate_secret_for_unified_accounts_once
  configure_firewall
  deploy_stack
  verify_stack

  log "Deployment complete. Open http://YOUR_DROPLET_IP:${PORT}"
}

main "$@"
