# PixelCraft 拼豆 — Deployment Guide

## Architecture

Two containers managed by Docker Compose:

| Container | Image | Role |
|---|---|---|
| `frontend` | nginx:1.27-alpine | Serves the React SPA; proxies `/api/*` to the backend |
| `backend` | python:3.11-slim | FastAPI app + Tesseract OCR + SQLite database |

Data is persisted in two named Docker volumes (`pindou_data`, `pindou_uploads`).

---

## Prerequisites

- **Docker** ≥ 24 — [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose** ≥ 2.20 (ships with Docker Desktop) — `docker compose version`

---

## Quick Start (local / dev)

```bash
# 1. Clone / enter the project directory
cd pindou

# 2. First launch — builds both images and starts everything
docker compose up --build

# 3. Open http://localhost in your browser
```

The backend seeds 8 demo patterns on first run. Subsequent restarts skip seeding.

Stop with `Ctrl+C`, or run detached:

```bash
docker compose up --build -d
docker compose logs -f   # follow logs
docker compose down      # stop and remove containers (volumes are kept)
```

---

## Production Setup

For a one-server DigitalOcean Ubuntu deployment, use the dedicated guide and bootstrap script:

- `DIGITALOCEAN_UBUNTU_DEPLOYMENT.md`
- `scripts/deploy_digitalocean_ubuntu.sh`

For an Amazon Lightsail Ubuntu instance, use the launch-script guide:

- `LIGHTSAIL_UBUNTU_LAUNCH.md`
- `scripts/lightsail_launch_ubuntu.sh`

### 1. Set a secure secret key

```bash
cp .env.example .env
# Generate a random key:
python3 -c "import secrets; print(secrets.token_hex(32))"
# Paste the output as SECRET_KEY in .env
```

### 2. (Optional) Change the port

Edit `.env`:
```
PORT=8080
```

### 3. Build and run

```bash
docker compose --env-file .env up --build -d
```

### 4. Verify

```bash
# Backend health
curl http://localhost/api/patterns        # should return JSON array

# Container status
docker compose ps
```

---

## Creating an Admin Account

Register through the UI with an email that contains `admin` (e.g. `admin@myfunlab.com`). The backend automatically grants admin privileges based on the email substring.

To upgrade an existing user to admin via SQLite:

```bash
docker compose exec backend python3 - <<'EOF'
from database import SessionLocal
import models
db = SessionLocal()
user = db.query(models.User).filter(models.User.email == "your@email.com").first()
user.is_admin = True
db.commit()
print("Done")
EOF
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `pixelcraft-change-this-in-production` | JWT signing secret — **must be changed in production** |
| `DATABASE_URL` | `sqlite:////app/data/pindou.db` | SQLAlchemy database URL |
| `PORT` | `80` | Host port the frontend listens on |
| `OPENAI_API_KEY` | unset | Enables preview-stage AI image enhancement and JSON bead-grid generation after the first photo conversion |
| `OPENAI_BASE_URL` | unset | Optional OpenAI-compatible base URL override |
| `OPENAI_IMAGE_MODEL` | `gpt-image-1.5` | OpenAI image model used for bead-friendly enhancement |
| `OPENAI_IMAGE_SIZE` | `1024x1024` | Output size for the preview enhancement image |
| `OPENAI_IMAGE_QUALITY` | `medium` | Output quality for the preview enhancement image |
| `OPENAI_IMAGE_MODERATION` | `low` | Official OpenAI moderation setting for GPT image models; use `auto` for stricter default filtering |
| `OPENAI_GRID_MODEL` | `gpt-4.1-mini` | OpenAI vision/text model used to return structured bead-grid JSON |
| `OPENAI_GRID_MAX_OUTPUT_TOKENS` | `60000` | Max output tokens for OpenAI grid JSON, needed for larger 78×78 and 104×104 grids |
| `OPENAI_REQUEST_TIMEOUT` | `45` | Max seconds to wait before the OpenAI enhancement request fails |

---

## Data & Backups

SQLite database and uploaded images live in named Docker volumes:

```bash
# Inspect volume location
docker volume inspect pindou_pindou_data

# Backup database
docker compose exec backend sqlite3 /app/data/pindou.db ".backup '/app/data/backup.db'"
docker cp $(docker compose ps -q backend):/app/data/backup.db ./backup.db

# Restore
docker cp ./backup.db $(docker compose ps -q backend):/app/data/pindou.db
docker compose restart backend
```

---

## Updating

```bash
git pull                          # get latest code
docker compose up --build -d      # rebuild images and restart
```

Old image layers are replaced; volumes (data) are untouched.

---

## Logs & Troubleshooting

```bash
docker compose logs backend       # FastAPI / Uvicorn logs
docker compose logs frontend      # nginx access/error logs
docker compose logs -f            # follow all logs live
```

**Image processing fails (admin upload):** Tesseract is installed in the backend image and handles JPEG/PNG/WEBP. If OCR quality is poor, try images with clear, solid-color regions and high contrast.

**Port 80 already in use:** Set `PORT=8080` in `.env` and access via `http://localhost:8080`.

**Database locked / corruption:** Stop all containers (`docker compose down`), then restart. SQLite WAL mode is not enabled by default — avoid running multiple backend replicas against the same SQLite file.

---

## Scaling Considerations

For production traffic beyond a single server:

1. Replace SQLite with **PostgreSQL** — update `DATABASE_URL` to `postgresql://user:pass@host/db` and add `psycopg2-binary` to `requirements.txt`.
2. Point `pindou_uploads` at an **object storage bucket** (S3 / R2) or a shared NFS mount if running multiple backend replicas.
3. Put a **reverse proxy / load balancer** (Caddy, Traefik, AWS ALB) in front of the frontend container to handle TLS termination.
