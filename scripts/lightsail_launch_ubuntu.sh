#!/usr/bin/env bash
set -Eeuo pipefail

# Paste this whole file into the Amazon Lightsail "Launch script" box.
# Replace REPO_URL with your Git repository URL before launching.
REPO_URL="${REPO_URL:-https://github.com/wingchee/funlab.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/pixelcraft}"
PORT="${PORT:-80}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-pixelcraft}"
ENABLE_UFW="${ENABLE_UFW:-true}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"

LOG_FILE="/var/log/pixelcraft-lightsail-launch.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

log() {
  printf '\n[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

require_ubuntu() {
  [[ -r /etc/os-release ]] || fail "This launch script expects Ubuntu."
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || fail "Unsupported OS '${ID:-unknown}'. Choose an Ubuntu Lightsail blueprint."
}

install_base_packages() {
  log "Installing base packages"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git gnupg lsb-release openssl ufw
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker and Docker Compose plugin are already installed"
    return
  fi

  log "Installing Docker Engine and Compose plugin"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /tmp/docker.asc
  rm -f /etc/apt/keyrings/docker.gpg
  gpg --dearmor -o /etc/apt/keyrings/docker.gpg /tmp/docker.asc
  chmod a+r /etc/apt/keyrings/docker.gpg

  # shellcheck disable=SC1091
  . /etc/os-release
  arch="$(dpkg --print-architecture)"
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' "${arch}" "${VERSION_CODENAME}" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

fetch_project() {
  if [[ -f "${APP_DIR}/docker-compose.yml" ]]; then
    log "Project already exists at ${APP_DIR}; using existing files"
    return
  fi

  [[ -n "${REPO_URL}" ]] || fail "Set REPO_URL at the top of this launch script before creating the Lightsail instance."

  log "Cloning PixelCraft from ${REPO_URL}"
  rm -rf "${APP_DIR}"
  git clone --branch "${REPO_BRANCH}" --single-branch "${REPO_URL}" "${APP_DIR}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local env_file="${APP_DIR}/.env"

  if grep -q "^${key}=" "${env_file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${env_file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${env_file}"
  fi
}

prepare_env() {
  log "Preparing application environment"
  cd "${APP_DIR}"

  if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
      cp .env.example .env
    else
      touch .env
    fi
  fi

  current_secret="$(grep '^SECRET_KEY=' .env | cut -d= -f2- || true)"
  if [[ -z "${current_secret}" || "${current_secret}" == "pixelcraft-change-this-in-production" ]]; then
    set_env_value "SECRET_KEY" "$(openssl rand -hex 32)"
  fi

  set_env_value "PORT" "${PORT}"
  set_env_value "COMPOSE_PROJECT_NAME" "${COMPOSE_PROJECT_NAME}"
  if [[ -n "${OPENAI_API_KEY}" ]]; then
    set_env_value "OPENAI_API_KEY" "${OPENAI_API_KEY}"
  fi

  chmod 600 .env
}

configure_firewall() {
  if [[ "${ENABLE_UFW}" != "true" ]]; then
    log "Skipping UFW because ENABLE_UFW is not true"
    return
  fi

  log "Configuring instance firewall"
  ufw allow OpenSSH
  ufw allow "${PORT}/tcp"
  ufw --force enable
}

deploy_stack() {
  log "Building and starting PixelCraft"
  cd "${APP_DIR}"
  docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env up --build -d
}

verify_stack() {
  log "Waiting for PixelCraft on http://127.0.0.1:${PORT}"

  for attempt in $(seq 1 45); do
    if curl -fsS --max-time 10 "http://127.0.0.1:${PORT}/api/patterns" >/dev/null; then
      log "PixelCraft is responding"
      docker compose --project-name "${COMPOSE_PROJECT_NAME}" ps
      return
    fi
    sleep 2
  done

  docker compose --project-name "${COMPOSE_PROJECT_NAME}" ps || true
  docker compose --project-name "${COMPOSE_PROJECT_NAME}" logs --tail=160 || true
  fail "PixelCraft did not respond on http://127.0.0.1:${PORT}/api/patterns"
}

main() {
  log "Starting PixelCraft Lightsail launch"
  require_ubuntu
  install_base_packages
  install_docker
  fetch_project
  prepare_env
  configure_firewall
  deploy_stack
  verify_stack
  log "Launch complete. Also open port ${PORT} in the Lightsail Networking tab, then visit http://YOUR_LIGHTSAIL_PUBLIC_IP:${PORT}"
}

main "$@"
