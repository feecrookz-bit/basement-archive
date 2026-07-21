# RUNBOOK — accounts, keys, and costs

This repo contains **two independent systems**, each with its own compose stack:

| System | Where | What it does | Money at risk |
|---|---|---|---|
| **Memecoin Tracker** | repo root (`app/`) | Solana memecoin discovery + wallet-signal + paper ledger (momentum / moonshot / graduation) | None — measurement only, never trades |
| **Sentinel** | `sentinel/` | Binance altcoin day-trading engine, paper-default with a triple-locked live gate | None in paper mode; real capital only after the 30-day gate |

---

## 1 · Accounts & keys

### Required

| Account | Used by | Cost | What it unlocks / what breaks without it |
|---|---|---|---|
| **Helius** ([helius.dev](https://helius.dev)) | Tracker | Free tier is enough to start; **paid plan (≈ $49/mo) only for real-time `WALLET_MODE=ws`** | The whole wallet-signal side. Free tier: **`WALLET_MODE=poll` (default) — outbound-only, NO public URL needed, ~45 s latency, Enhanced-API parsing that sees terminal-vault trades** — or `webhook` (needs a public URL, near-real-time). No key at all → discovery + gates degrade, wallet tracking off. |
| **GitHub** | both | Free | You have this. Codespaces free tier: ~120 core-hours/mo on personal accounts. |

### Not required (no account, no key)

| Source | Used by | Notes |
|---|---|---|
| DEX Screener | Tracker | Public REST; 60 req/min discovery, 300 req/min pair lookups — the defaults respect both |
| PumpPortal WS | Tracker (graduation watcher) | `subscribeNewToken` / `subscribeMigration` are free, keyless |
| Binance public data | Tracker (Alpha/announcements) + **Sentinel paper mode** | Klines, tickers, funding, OI — all public. **Sentinel paper mode needs zero keys.** |

### Optional

| Account | Used by | Cost | Purpose |
|---|---|---|---|
| Discord webhook | Tracker | Free | Alerts (`DISCORD_WEBHOOK_URL`) — silent no-op if unset |
| Telegram bot (@BotFather) | Tracker | Free | Alerts (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) |
| Token-unlock data API | Sentinel Scout | Free CSV by hand; paid APIs optional | Ships as `sentinel/data/unlocks.csv` stub. **Empty calendar = unlock guard OFF.** |
| **Binance exchange account** | **Sentinel LIVE only** | Free account; KYC required | API key + secret in `.env`. Not needed until you deliberately go live (see §4). Region caveat: Binance is unavailable/restricted in some jurisdictions (US uses Binance.US with a different API) — your problem to verify locally. |

---

## 2 · Running costs

### The $0 path (works today)
- **Where:** GitHub Codespaces free tier (or any machine with Docker).
- **Tracker:** `WALLET_MODE=webhook` + Helius free tier + a free tunnel (Cloudflare Tunnel) for the public webhook URL. Discovery, gates, moonshot, graduation, Binance-events all run.
- **Sentinel:** paper mode, keyless.
- **Caveats:** Codespaces sleeps when idle — fine for trying it out, useless for 24/7 signal collection. Free Helius credits can run out if you track many wallets / enable holder counting aggressively (`HOLDER_COUNT_MAX_PAGES=0` to disable).

### The serious path (~$55–75/mo)
- **VPS** for 24/7 uptime: ~$5–20/mo (Hetzner/DigitalOcean, 2 vCPU / 4 GB runs both stacks). Both systems are useless if they aren't awake when the signal happens.
- **Helius paid entry tier** ≈ $49/mo → `WALLET_MODE=ws` (Atlas `transactionSubscribe`, real-time, no public URL needed) + comfortable RPC headroom.
- Everything else stays $0.

### Live trading costs (Sentinel only, after the gate)
- Binance spot fees: **0.1% taker** per fill (the paper model assumes exactly this; ~25% discount paying fees in BNB).
- Slippage: real, unmodelled beyond the paper assumptions — expect live ≤ paper.
- **Capital**: whatever you fund the account with is at risk. Sizing is 0.75%/trade with a 2% open-risk cap, but that limits pace of loss, not possibility.

---

## 3 · Bring-up

### VPS / home server (24/7 — the serious path)

One command on any Docker-capable Linux box — see **[deploy/README.md](deploy/README.md)**:

```bash
git clone https://github.com/feecrookz-bit/basement-archive && cd basement-archive
HELIUS_API_KEY=your-key bash deploy/bootstrap.sh --quick-tunnel
```

Installs Docker if needed, seeds env files, opens a free Cloudflare
tunnel for the Helius webhook (named-tunnel overlay available for a
stable URL), starts both stacks with restart policies, and prints status.

### Codespaces free-tier quickstart (Helius free plan, no VPS)

1. **Helius account** (2 min, only step outside GitHub): sign up at
   [helius.dev](https://helius.dev) → dashboard → copy your **API key**.
   The free plan is enough for webhook mode + the RPC safety gates.
2. **Create the Codespace**: repo page → Code → Codespaces → *Create
   codespace on main*. The devcontainer seeds both `.env` files.
3. **Add the key** — either way works:
   - *Recommended:* [github.com/settings/codespaces](https://github.com/settings/codespaces)
     → New secret → name `HELIUS_API_KEY`, value = your key, repository
     access = this repo. Every new Codespace injects it into `.env`
     automatically (see `.devcontainer/setup.sh`).
   - *Or* just paste `HELIUS_API_KEY=...` into `.env` in the Codespace.

   `WALLET_MODE=webhook` is already the `.env.example` default.
4. **Start the tracker**: `docker compose up --build` → dashboard opens on
   port 8000.
5. **Make port 8000 Public**: Ports panel → right-click 8000 → Port
   Visibility → **Public**. Helius must be able to reach
   `https://<codespace>-8000.app.github.dev/webhooks/helius`.
6. **Add wallets** in the dashboard. The app now **registers/updates the
   Helius webhook automatically** via their API (address list stays in
   sync on every add/remove) — no dashboard fiddling on helius.dev.
7. Optional, in a second terminal: `cd sentinel && docker compose up
   --build` → Sentinel papers away on ports 3000/8080 (keyless).

Codespaces caveats: the machine sleeps on idle (signals stop; webhook
deliveries fail while asleep) and the public URL changes per codespace —
the auto-sync fixes the webhook URL on next startup. Fine for evaluation;
move to a VPS for 24/7.

### Tracker (repo root)
```bash
cp .env.example .env        # add HELIUS_API_KEY; pick WALLET_MODE
docker compose up --build   # dashboard http://localhost:8000
```
- `WALLET_MODE=ws` (paid Helius) or `webhook` (free; create the webhook in the Helius dashboard pointing at https://your-url/webhooks/helius with your tracked addresses, type SWAP/Any).
- Add wallets via the dashboard or `POST /api/wallets` — **the wallet list is the product**; the ledger only measures the list you curate.
- Acceptance checklist: handover §5 (discovery rows ~30 s after start, wallet hit → signal → paper trade, etc.).

### Sentinel (`sentinel/`)
```bash
cd sentinel
cp .env.example .env        # nothing to fill for paper
docker compose up --build   # dashboard :3000 · api :8080
```
- Runs paper immediately. Let it collect ≥ 30 distinct paper-trade days.
- Read the Coach's weekly setup×regime breakdown before even thinking about live.

## 4 · Going live with Sentinel (deliberately annoying)

1. ≥ 30 distinct days of paper trades in the ledger (`/api/live` shows the gate progress; it is computed from the DB and cannot be faked via config).
2. Create a Binance API key: **enable spot trading only — disable withdrawals — IP-whitelist your server.** Put key/secret in `sentinel/.env`.
3. Set `mode.live: true` in `sentinel/config.yaml`.
4. Start workers with the CLI lock: `python -m sentinel run --confirm-live-i-accept-losses`.
5. A weekly −5% breaker halt only clears via `python -m sentinel resume --reason "..."` — the typed reason is stored forever.

All three locks (config + CLI + ledger history) must be open; anything less silently runs paper.

## 5 · Security notes

- `.env` is git-ignored in both stacks — keep it that way; never commit keys.
- The Binance key needs **no withdrawal permission, ever**. Trading-only + IP whitelist bounds the blast radius of a leak to bad trades, not stolen funds.
- Helius keys are spend-limited by plan credits — a leak wastes credits, rotate it in the dashboard.
- Both dashboards are unauthenticated by design (self-hosted, assumed private network). Don't port-forward them to the open internet; if you must expose them, put them behind a tunnel with auth (Cloudflare Access etc.).

## 6 · Honest cost of it all

The tracker's ledger and Sentinel's Coach exist to answer, cheaply, whether an edge exists **before** capital is committed. The realistic outcome for most operators is that the ledgers stay red net of fees and slippage — in which case the total cost of finding that out was one VPS, one Helius sub, and some patience, which is the cheapest tuition this market sells.
