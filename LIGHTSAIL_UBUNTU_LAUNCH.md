# PixelCraft Lightsail Launch Script

Use [scripts/lightsail_launch_ubuntu.sh](/Users/wingchee/Documents/Code/php_project/pindou%20copy%202/scripts/lightsail_launch_ubuntu.sh) as the Amazon Lightsail instance launch script for an Ubuntu instance.

## 1. Edit the Launch Script

Before pasting it into Lightsail, replace the empty `REPO_URL` value near the top:

```bash
REPO_URL="https://github.com/YOUR_ACCOUNT/YOUR_REPO.git"
REPO_BRANCH="main"
APP_DIR="/opt/pixelcraft"
PORT="80"
COMPOSE_PROJECT_NAME="pixelcraft"
OPENAI_API_KEY=""
```

If your repo is private, use a deploy key or a temporary HTTPS token URL. Do not paste your normal GitHub password into the script.

## 2. Create the Lightsail Instance

Recommended settings:

- Platform: Linux/Unix
- Blueprint: Ubuntu 24.04 LTS or Ubuntu 22.04 LTS
- Plan: at least 2 GB RAM; 4 GB RAM is safer for image processing
- Launch script: paste the edited contents of `scripts/lightsail_launch_ubuntu.sh`

The launch script installs Docker, clones the repo into `/opt/pixelcraft`, creates `.env`, starts Docker Compose, and writes logs to:

```text
/var/log/pixelcraft-lightsail-launch.log
```

## 3. Networking

In the Lightsail Networking tab, allow:

- `22/tcp` for SSH
- `80/tcp` for HTTP

The script also enables UFW inside Ubuntu and allows SSH plus the app port.

Open the app:

```text
http://YOUR_LIGHTSAIL_PUBLIC_IP
```

## 4. Check Launch Progress

SSH into the instance:

```bash
ssh ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP
```

View first-boot logs:

```bash
sudo tail -f /var/log/pixelcraft-lightsail-launch.log
```

Check containers:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft ps
```

Check the API:

```bash
curl -i http://127.0.0.1/api/patterns
```

## 5. Redeploy After Code Changes

```bash
ssh ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP
cd /opt/pixelcraft
sudo git pull
sudo docker compose --project-name pixelcraft --env-file .env up --build -d
```

## 6. Troubleshooting

If the page does not load:

```bash
sudo tail -n 200 /var/log/pixelcraft-lightsail-launch.log
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft logs --tail=200
sudo ufw status verbose
```

If port `80` is already used, change the script before launch:

```bash
PORT="8080"
```

Then allow `8080/tcp` in the Lightsail Networking tab and open:

```text
http://YOUR_LIGHTSAIL_PUBLIC_IP:8080
```
