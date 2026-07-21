# Deploying outside Codespaces

Anything that runs Docker 24/7 works: a $5 VPS (Hetzner/DigitalOcean/
Vultr), an old laptop or Raspberry Pi at home, Oracle Cloud's free ARM
tier. Requirements: Docker + compose, ~4 GB RAM for both stacks, outbound
internet, and one inbound public HTTPS route for `/webhooks/helius`
(tracker only — Sentinel needs no inbound at all).

## Quick start (VPS or home box)

```bash
git clone https://github.com/feecrookz-bit/basement-archive && cd basement-archive
HELIUS_API_KEY=your-key bash deploy/bootstrap.sh --quick-tunnel
```

That installs Docker if missing, seeds both `.env` files, starts a free
Cloudflare quick tunnel, writes its URL into `.env` as
`WEBHOOK_PUBLIC_URL`, and brings up both stacks. Add wallets via the
dashboard and the app registers the Helius webhook itself.

Quick-tunnel caveat: the `trycloudflare.com` URL changes every time the
tunnel restarts. The app re-registers the webhook on startup and on
wallet changes, so it self-heals — but for a permanent deployment use a
**named tunnel**:

## Stable URL (named Cloudflare tunnel, free)

1. Cloudflare Zero Trust → Networks → Tunnels → create a tunnel, copy its
   token.
2. Add a public hostname (e.g. `tracker.yourdomain.com`) pointing at
   service `http://app:8000`.
3. ```bash
   HELIUS_API_KEY=... WEBHOOK_PUBLIC_URL=https://tracker.yourdomain.com \
     TUNNEL_TOKEN=eyJ... bash deploy/bootstrap.sh
   ```

The tunnel container joins the compose network and reaches the app by
service name — you never expose a host port to the internet.

## Operations

- **Stop everything**: `bash deploy/bootstrap.sh --down`
- **Update**: `git pull && bash deploy/bootstrap.sh` (same flags as before)
- **Logs**: `docker compose logs -f app` · `cd sentinel && docker compose logs -f`
- All services carry `restart: unless-stopped` — they survive reboots once
  Docker itself is enabled (`systemctl enable docker`, default on most
  distros).

## Firewall

The dashboards are unauthenticated by design. On a VPS:

```bash
ufw default deny incoming && ufw allow ssh && ufw enable
```

Inbound webhook traffic rides the tunnel; you browse the dashboards over
an SSH port-forward (`ssh -L 8000:localhost:8000 -L 3000:localhost:3000
user@box`) or put Cloudflare Access in front of a tunnel hostname.

## Alternatives that also work

- **Oracle Cloud Always Free** — 4 ARM cores / 24 GB, $0. All images used
  here have arm64 builds. Signup friction and regional capacity are the
  price.
- **Fly.io / Railway / Render** — fine for Docker apps, but this repo is
  compose-first; you'd split services into their per-app model and use
  managed Postgres/Redis. Only worth it if you're already invested there.
- **Codespaces** — great for development, wrong for signal collection:
  it sleeps on idle and the public URL rotates.
