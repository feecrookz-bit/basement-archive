# Operations

> Full account/key/cost table: [RUNBOOK.md](../../RUNBOOK.md). This page is
> the operational shape; the runbook is the checklist.

## Running the tracker

```bash
cp .env.example .env        # add HELIUS_API_KEY
docker compose up --build   # dashboard: http://localhost:8000
```

Key modes:
- `DISCOVERY_MODE`: `poll` (official DEX Screener REST, default) | `ws`
- `WALLET_MODE`: `poll` (**default — free tier, outbound-only, no public
  URL needed**) | `webhook` (free tier + public URL) | `ws` (Helius Atlas,
  paid) | `off`

The only required key is Helius (free tier works). Everything else —
DEX Screener, PumpPortal, Binance public endpoints, CoinGecko global —
is keyless.

## Running Sentinel

```bash
cd sentinel
cp .env.example .env
docker compose up --build   # dashboard :3000 · api :8080
```

Paper mode needs **no keys at all** — live public Binance market data,
simulated fills (taker fee + spread/impact slippage). Binance API keys
enter the picture only at live trading, behind the
[triple gate](Sentinel-Strategy.md#the-paper--live-gate).

### Sign-in

Set `DASHBOARD_PASSWORD` and the dashboard grows a login page; every
`/api/*` route except `/api/health` + auth routes 401s without the
HMAC-signed session cookie (7-day expiry, httpOnly). Set `SESSION_SECRET`
to keep sessions across restarts. Unset = auth off (localhost use).
Single-operator by design: one password, no accounts, no OAuth.

### Notifications

Set any of `DISCORD_WEBHOOK_URL` or `TELEGRAM_BOT_TOKEN` +
`TELEGRAM_CHAT_ID`. Pushes fire **only** on: trade opened, each exit
(TP1/TP2/stop/trail with realized R), circuit-breaker halts, coach
reports, and the one-time paper→live gate opening. Alert failures are
swallowed — a dead webhook can never touch trading. The same events feed
the dashboard's Activity panel.

## Where to host

Three tiers, documented in [deploy/](../../deploy/):

| option | cost | fit |
|---|---|---|
| GitHub Codespaces | free tier hours | development, demos |
| cheap VPS (2 GB) | ~$5–8/mo | 24/7 both systems — the sweet spot |
| home server + cloudflared tunnel | $0 + electricity | if you own hardware |

`deploy/bootstrap.sh` takes a fresh Ubuntu VPS to running services
(Docker, compose files, restart policies); the tunnel compose file adds a
public HTTPS URL without opening ports — which is also the cheapest way
to get a webhook-capable URL for `WALLET_MODE=webhook`.

## Testing

```bash
cd sentinel && pytest -q          # 118 tests, no infra
cd web && npm run build           # dashboard must build clean
```

Full browser E2E (what CI runs as `sentinel-e2e`):

```bash
docker compose up -d db
python scripts/seed_demo.py
DASHBOARD_PASSWORD=e2e-pass uvicorn sentinel.api:app --port 8080 &
cd web && npm run build && npx next start -p 3000 &
cd ../e2e && npm i && npx playwright test    # 8 specs incl. mobile
```

## Operational hygiene

- **Never commit `.env`** — both `.gitignore`s exclude it. Rotate any key
  that was ever pasted into a chat, issue, or screenshot.
- The paper ledgers are the deliverable of the first month. Do not
  shortcut the 30-day Sentinel gate; do not add wallets to the tracker
  without vetting (`scripts/vet_wallets.py`).
- Config changes are deploys: Sentinel snapshots `config.yaml` on boot
  and the dashboard shows version history — edit, restart, verify the new
  version id.
