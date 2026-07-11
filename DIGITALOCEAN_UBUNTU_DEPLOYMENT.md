# Deploy PixelCraft to a DigitalOcean Ubuntu Droplet

This guide deploys PixelCraft with Docker Compose on one Ubuntu droplet. It runs:

- `frontend`: nginx serving the SPA and proxying `/api/*`
- `backend`: FastAPI, SQLite, uploads, image processing, and Tesseract OCR
- Docker volumes: `pixelcraft_pindou_data` and `pixelcraft_pindou_uploads`

The included script installs Docker, creates a production `.env`, configures UFW, builds the containers, starts them, and checks the app.

## 1. Create the Droplet

Recommended baseline:

- Ubuntu 24.04 LTS or 22.04 LTS
- 2 GB RAM minimum; 4 GB RAM is safer for image processing
- SSH key login enabled
- Inbound ports: `22`, `80`

If you plan to put a reverse proxy or CDN in front later, still start with HTTP on port `80` first so deployment is easy to verify.

## 2. Copy the Project to the Droplet

Option A: clone from Git, if this repo is available remotely:

```bash
ssh root@YOUR_DROPLET_IP
mkdir -p /opt
git clone YOUR_REPO_URL /opt/pixelcraft
cd /opt/pixelcraft
```

Option B: upload your local folder from your computer:

```bash
cd "/Users/wingchee/Documents/Code/php_project"
tar \
  --exclude='pindou copy 2/.env' \
  --exclude='pindou copy 2/perler-beads-master/node_modules' \
  --exclude='pindou copy 2/perler-beads-master/.next' \
  --exclude='pindou copy 2/BeanBuddy-AI-main/frontend/node_modules' \
  -czf pixelcraft.tar.gz "pindou copy 2"
scp pixelcraft.tar.gz root@YOUR_DROPLET_IP:/opt/
ssh root@YOUR_DROPLET_IP
cd /opt
tar -xzf pixelcraft.tar.gz
mv "pindou copy 2" pixelcraft
cd /opt/pixelcraft
```

## 3. Run the Deployment Script

```bash
chmod +x scripts/deploy_digitalocean_ubuntu.sh
sudo APP_DIR=/opt/pixelcraft PORT=80 COMPOSE_PROJECT_NAME=pixelcraft scripts/deploy_digitalocean_ubuntu.sh
```

When it finishes, open:

```text
http://YOUR_DROPLET_IP
```

The script verifies:

```text
http://127.0.0.1:80/api/patterns
```

## 4. Configure Environment Variables

The script creates `/opt/pixelcraft/.env` from `.env.example` if needed and replaces the default `SECRET_KEY` with a random value.

Edit production values:

```bash
nano /opt/pixelcraft/.env
```

Common values:

```dotenv
PORT=80
COMPOSE_PROJECT_NAME=pixelcraft
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_IMAGE_MODEL=gpt-image-1.5
OPENAI_GRID_MODEL=gpt-4.1-mini
```

Apply changes:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft --env-file .env up --build -d
```

## 5. Routine Operations

View containers:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft ps
```

Follow logs:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft logs -f
```

Restart:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft restart
```

Stop:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft down
```

Update after uploading or pulling new code:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft --env-file .env up --build -d
```

## 6. Backups

Before each container start, the deployment script checks for
`pixelcraft_pindou_data`. If the database exists, it creates a timestamped backup
outside that volume, such as
`/opt/pixelcraft/backups/pindou-20260712-153000.db`, and prints the verified path.
The script uses SQLite's online backup API and `PRAGMA integrity_check`; a copy or
integrity failure aborts deployment before migrations start.

For Git checkouts, the script also writes the current revision to
`/opt/pixelcraft/.previous-deploy-commit`. Uploaded source folders without Git
metadata cannot provide commit rollback, so retain the prior uploaded release too.

The unified-account release rotates `SECRET_KEY` once after the verified backup and
persists a marker in `.env`. This intentionally signs all users out once. Repeated
deployments keep the rotated key.

Back up the SQLite database:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft exec backend python3 - <<'PY'
import sqlite3
src = sqlite3.connect("/app/data/pindou.db")
dst = sqlite3.connect("/app/data/backup.db")
src.backup(dst)
dst.close()
src.close()
PY
sudo docker cp "$(sudo docker compose --project-name pixelcraft ps -q backend):/app/data/backup.db" ./backup.db
```

Back up uploaded images:

```bash
cd /opt/pixelcraft
sudo docker run --rm -v pixelcraft_pindou_uploads:/uploads -v "$PWD":/backup alpine \
  tar -czf /backup/uploads.tar.gz -C /uploads .
```

Copy backups to your computer:

```bash
scp root@YOUR_DROPLET_IP:/opt/pixelcraft/backup.db .
scp root@YOUR_DROPLET_IP:/opt/pixelcraft/uploads.tar.gz .
```

### Roll back a migration deployment

The `BACKUP` command selects the newest verified backup printed by the deployment
script. To restore an older point, replace it with that exact
`/opt/pixelcraft/backups/pindou-*.db` path. Git-based deployments can then restore
the revision recorded before deployment:

```bash
cd /opt/pixelcraft
BACKUP="$(ls -1t /opt/pixelcraft/backups/pindou-*.db | head -n 1)"
PREVIOUS_COMMIT="$(cat /opt/pixelcraft/.previous-deploy-commit)"
sudo docker compose --project-name pixelcraft --env-file .env down
MOUNTPOINT="$(sudo docker volume inspect pixelcraft_pindou_data --format '{{ .Mountpoint }}')"
sudo install -m 0600 "${BACKUP}" "${MOUNTPOINT}/pindou.db"
sudo git checkout "${PREVIOUS_COMMIT}"
sudo docker compose --project-name pixelcraft --env-file .env up --build -d
```

Never use `docker compose down -v` during rollback. The `-v` option deletes the
named database and upload volumes.

## 7. Optional HTTPS

The app works on HTTP through the frontend container. For HTTPS, use one of these:

- Point your domain to the droplet and put Cloudflare in front with proxy/TLS enabled.
- Use a DigitalOcean Load Balancer with a managed certificate.
- Install Caddy or nginx on the host and move the app to an internal port such as `PORT=8080`.

For a host reverse proxy, change `.env`:

```dotenv
PORT=8080
```

Then redeploy:

```bash
cd /opt/pixelcraft
sudo PORT=8080 APP_DIR=/opt/pixelcraft COMPOSE_PROJECT_NAME=pixelcraft scripts/deploy_digitalocean_ubuntu.sh
```

Your reverse proxy should forward traffic to:

```text
http://127.0.0.1:8080
```

## 8. Troubleshooting

Check health through nginx:

```bash
curl -i http://127.0.0.1/api/patterns
```

Check backend health from inside Docker:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft exec backend curl -i http://127.0.0.1:8000/health
```

If port 80 is already used:

```bash
cd /opt/pixelcraft
sudo PORT=8080 APP_DIR=/opt/pixelcraft COMPOSE_PROJECT_NAME=pixelcraft scripts/deploy_digitalocean_ubuntu.sh
```

If the firewall blocks traffic:

```bash
sudo ufw status verbose
sudo ufw allow 80/tcp
```

If image processing fails, inspect backend logs:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft logs --tail=200 backend
```

Tesseract OCR is installed inside the backend Docker image. You do not need to install it separately on the droplet.
