# PixelCraft Lightsail SSH Deploy

Use this when the Amazon Lightsail instance already exists. For a brand-new instance, the first-boot launch script in `LIGHTSAIL_UBUNTU_LAUNCH.md` is still available.

## 1. Create Or Open The Instance

Recommended Lightsail settings:

- Platform: Linux/Unix
- Blueprint: Ubuntu 24.04 LTS or Ubuntu 22.04 LTS
- Plan: at least 2 GB RAM; 4 GB RAM is safer for image processing

In the Lightsail **Networking** tab, allow:

- `22/tcp` for SSH
- `80/tcp` for HTTP

## 2. Public Repo One-Command Deploy

SSH into the instance:

```bash
ssh ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP
```

Run the deploy script from your repository:

```bash
REPO_BRANCH=main
curl -fsSL "https://raw.githubusercontent.com/YOUR_ACCOUNT/YOUR_REPO/${REPO_BRANCH}/scripts/deploy_lightsail_ubuntu.sh" \
  | sudo env REPO_URL=https://github.com/YOUR_ACCOUNT/YOUR_REPO.git REPO_BRANCH="${REPO_BRANCH}" APP_DIR=/opt/pixelcraft COMPOSE_PROJECT_NAME=pixelcraft bash
```

Optional values:

```bash
REPO_BRANCH=main
curl -fsSL "https://raw.githubusercontent.com/YOUR_ACCOUNT/YOUR_REPO/${REPO_BRANCH}/scripts/deploy_lightsail_ubuntu.sh" \
  | sudo env REPO_URL=https://github.com/YOUR_ACCOUNT/YOUR_REPO.git REPO_BRANCH="${REPO_BRANCH}" APP_DIR=/opt/pixelcraft COMPOSE_PROJECT_NAME=pixelcraft PORT=80 OPENAI_API_KEY=your_key_here bash
```

The script installs Docker, clones or updates the repo in `/opt/pixelcraft`, prepares `.env`, starts Docker Compose, and verifies the app locally.

## 3. Private Repo Path

For a private repo, avoid putting access tokens into shell history. Clone with SSH or a deploy key first:

```bash
ssh ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP
sudo apt-get update
sudo apt-get install -y git
sudo git clone git@github.com:YOUR_ACCOUNT/YOUR_REPO.git /opt/pixelcraft
sudo APP_DIR=/opt/pixelcraft /opt/pixelcraft/scripts/deploy_lightsail_ubuntu.sh
```

If you need OpenAI features:

```bash
sudo OPENAI_API_KEY=your_key_here APP_DIR=/opt/pixelcraft /opt/pixelcraft/scripts/deploy_lightsail_ubuntu.sh
```

## 4. Check Progress

Deployment logs:

```bash
sudo tail -f /var/log/pixelcraft-lightsail-deploy.log
```

Container status:

```bash
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft ps
```

Local API check:

```bash
curl -i http://127.0.0.1/api/patterns
```

Open the app:

```text
http://YOUR_LIGHTSAIL_PUBLIC_IP
```

## 5. Redeploy After Code Changes

```bash
ssh ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP
REPO_BRANCH=main
curl -fsSL "https://raw.githubusercontent.com/YOUR_ACCOUNT/YOUR_REPO/${REPO_BRANCH}/scripts/deploy_lightsail_ubuntu.sh" \
  | sudo env REPO_URL=https://github.com/YOUR_ACCOUNT/YOUR_REPO.git REPO_BRANCH="${REPO_BRANCH}" APP_DIR=/opt/pixelcraft COMPOSE_PROJECT_NAME=pixelcraft bash
```

Fetching the script from the requested branch guarantees that the rollout starts with
the new deployment safeguards. The script runs `git pull --ff-only`, re-executes the
checked-out copy once, rebuilds containers, and keeps Docker volumes plus `.env`.

## 6. Troubleshooting

If the page does not load:

```bash
sudo tail -n 200 /var/log/pixelcraft-lightsail-deploy.log
cd /opt/pixelcraft
sudo docker compose --project-name pixelcraft logs --tail=200
sudo ufw status verbose
```

If port `80` is already used:

```bash
sudo PORT=8080 /opt/pixelcraft/scripts/deploy_lightsail_ubuntu.sh
```

Then allow `8080/tcp` in the Lightsail Networking tab and open:

```text
http://YOUR_LIGHTSAIL_PUBLIC_IP:8080
```
