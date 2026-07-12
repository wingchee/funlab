# Cloudflare Quick Tunnel Design

## Goal

Provide a temporary public URL for the local PixelCraft Docker stack so an external tester can use the application without a Cloudflare account, domain, or tunnel token.

## Architecture

Add a `cloudflared` service to `docker-compose.yml` behind an explicit `share` profile. The service joins the existing Compose network and proxies a Cloudflare Quick Tunnel to `http://frontend:80`. Only the nginx frontend is exposed through the tunnel; nginx continues to proxy `/api/*` and `/bead-editor/*` internally, while the backend, database volume, uploads volume, and bead editor remain unreachable as direct public origins.

Normal `docker compose up` behavior remains unchanged because the new service runs only when the `share` profile is enabled.

## Operator Workflow

Add `scripts/share_with_cloudflare.sh` as the supported entrypoint. It will:

1. Start the existing application services.
2. Recreate the `cloudflared` Quick Tunnel container under the `share` profile.
3. Poll the container logs for the generated HTTPS `trycloudflare.com` URL.
4. Print the URL and the command used to stop sharing.
5. Exit with a useful error and recent tunnel logs if no URL appears within a bounded timeout.

The tunnel remains active after the script exits. Operators stop public access with `docker compose --profile share stop cloudflared`.

## Security and Lifecycle

- The generated URL is public and unauthenticated; application authentication still applies to protected actions.
- Quick Tunnels are for testing only and have no uptime guarantee.
- No Cloudflare credentials or tokens are stored in the repository or environment files.
- Restarting or recreating the Quick Tunnel may generate a different URL.
- The tunnel service will not publish additional host ports.

## Verification

- Add source-level regression tests for the Compose service, explicit profile, internal frontend target, helper script, and documentation.
- Validate the merged Compose configuration.
- Start the Quick Tunnel through Docker and confirm a `trycloudflare.com` URL is generated.
- Request the frontend and `/api/patterns` through the public URL and require HTTP 200 responses.
- Run the full existing test suite and `git diff --check`.
