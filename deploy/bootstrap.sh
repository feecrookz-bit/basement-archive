#!/usr/bin/env bash
# =============================================================================
# One-command deploy for the crypto monorepo on any Docker-capable Linux box
# (VPS, home server, Raspberry Pi). Idempotent — safe to re-run.
#
# Usage (from the repo root, after git clone):
#
#   HELIUS_API_KEY=your-key bash deploy/bootstrap.sh --quick-tunnel
#       Tracker + Sentinel + a free Cloudflare *quick* tunnel. The tunnel URL
#       is scraped from cloudflared's logs and written into .env as
#       WEBHOOK_PUBLIC_URL *before* the tracker starts, so the Helius webhook
#       registers automatically. Quick-tunnel URLs change on every restart —
#       fine for getting started; use a named tunnel for a stable URL.
#
#   HELIUS_API_KEY=... WEBHOOK_PUBLIC_URL=https://your.domain \
#     TUNNEL_TOKEN=eyJ... bash deploy/bootstrap.sh
#       Named Cloudflare tunnel (stable URL): create the tunnel in the
#       Cloudflare Zero Trust dashboard, point a public hostname at
#       http://app:8000, pass its token. Runs via the compose overlay.
#
#   bash deploy/bootstrap.sh --no-sentinel     # tracker only
#   bash deploy/bootstrap.sh --down            # stop everything
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

QUICK_TUNNEL=0
WITH_SENTINEL=1
for arg in "$@"; do
  case "$arg" in
    --quick-tunnel) QUICK_TUNNEL=1 ;;
    --no-sentinel)  WITH_SENTINEL=0 ;;
    --down)
      docker compose down || true
      (cd sentinel && docker compose down) || true
      docker rm -f crypto-quick-tunnel 2>/dev/null || true
      echo "deploy: everything stopped"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# ---- 1. docker ---------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "deploy: installing docker..."
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null

# ---- 2. env files ------------------------------------------------------------
[ -f .env ] || cp .env.example .env
[ -f sentinel/.env ] || cp sentinel/.env.example sentinel/.env

if [ -n "${HELIUS_API_KEY:-}" ] && grep -q '^HELIUS_API_KEY=$' .env; then
  sed -i.bak "s|^HELIUS_API_KEY=$|HELIUS_API_KEY=${HELIUS_API_KEY}|" .env && rm -f .env.bak
  echo "deploy: HELIUS_API_KEY written to .env"
fi
if ! grep -q '^HELIUS_API_KEY=.\+' .env; then
  echo "deploy: WARNING — no HELIUS_API_KEY in .env; wallet tracking and" \
       "safety gates will be degraded (see RUNBOOK.md)"
fi

# ---- 3. public URL for the Helius webhook ------------------------------------
if [ "$QUICK_TUNNEL" = "1" ]; then
  echo "deploy: starting Cloudflare quick tunnel..."
  docker rm -f crypto-quick-tunnel 2>/dev/null || true
  docker run -d --name crypto-quick-tunnel --restart unless-stopped \
    --network host cloudflare/cloudflared:latest \
    tunnel --no-autoupdate --url http://localhost:8000 >/dev/null
  URL=""
  for _ in $(seq 1 30); do
    URL=$(docker logs crypto-quick-tunnel 2>&1 |
          grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1 || true)
    [ -n "$URL" ] && break
    sleep 2
  done
  if [ -z "$URL" ]; then
    echo "deploy: ERROR — quick tunnel URL never appeared; check:" >&2
    echo "  docker logs crypto-quick-tunnel" >&2
    exit 1
  fi
  echo "deploy: tunnel up at $URL"
  sed -i.bak "s|^WEBHOOK_PUBLIC_URL=.*|WEBHOOK_PUBLIC_URL=${URL}|" .env && rm -f .env.bak
elif [ -n "${WEBHOOK_PUBLIC_URL:-}" ]; then
  sed -i.bak "s|^WEBHOOK_PUBLIC_URL=.*|WEBHOOK_PUBLIC_URL=${WEBHOOK_PUBLIC_URL}|" .env && rm -f .env.bak
  echo "deploy: WEBHOOK_PUBLIC_URL=${WEBHOOK_PUBLIC_URL}"
else
  echo "deploy: no public URL — fine: the default WALLET_MODE=poll collects"
  echo "  wallet signals outbound-only (no tunnel needed). Use --quick-tunnel"
  echo "  or WEBHOOK_PUBLIC_URL=... only if you switch to WALLET_MODE=webhook."
fi

# ---- 4. tracker stack --------------------------------------------------------
if [ -n "${TUNNEL_TOKEN:-}" ]; then
  echo "deploy: starting tracker + named cloudflare tunnel..."
  TUNNEL_TOKEN="$TUNNEL_TOKEN" docker compose \
    -f docker-compose.yml -f deploy/docker-compose.tunnel.yml up -d --build
else
  docker compose up -d --build
fi

# ---- 5. sentinel stack -------------------------------------------------------
if [ "$WITH_SENTINEL" = "1" ]; then
  (cd sentinel && docker compose up -d --build)
fi

# ---- 6. status ---------------------------------------------------------------
sleep 5
echo
echo "==================== deploy status ===================="
curl -sf localhost:8000/api/discovery?limit=1 >/dev/null \
  && echo "tracker    : UP  http://localhost:8000" \
  || echo "tracker    : starting (check: docker compose logs app)"
if [ "$WITH_SENTINEL" = "1" ]; then
  curl -sf localhost:8080/api/health >/dev/null \
    && echo "sentinel   : UP  api :8080 · dashboard :3000" \
    || echo "sentinel   : starting (check: cd sentinel && docker compose logs)"
fi
grep -q '^WEBHOOK_PUBLIC_URL=.\+' .env \
  && echo "webhook URL: $(grep '^WEBHOOK_PUBLIC_URL=' .env | cut -d= -f2-)" \
  || echo "webhook URL: NOT SET (wallet signals off)"
echo "next       : add wallets via the dashboard or POST /api/wallets —"
echo "             the app registers the Helius webhook automatically."
echo "firewall   : keep 8000/3000/8080 private (ufw allow ssh only);"
echo "             the tunnel handles inbound webhook traffic."
echo "======================================================="
