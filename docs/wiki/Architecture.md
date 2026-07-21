# Architecture

## Monorepo layout

```
/                       Memecoin Tracker (FastAPI, app/)
├── app/                tracker modules (discovery, wallets, signals, …)
├── scripts/            vet_wallets.py — on-chain wallet vetting CLI
├── docs/               WALLETS.md research + this wiki
├── deploy/             VPS/home-server bootstrap + cloudflared tunnel
├── sentinel/           Sentinel engine (own docker-compose, own tests)
│   ├── sentinel/       python package: api, workers, ledger, modules/
│   ├── web/            Next.js 14 dashboard (dark/amber FATBot styling)
│   ├── e2e/            Playwright browser suite
│   ├── scripts/        seed_demo.py — demo data through the real ledger
│   └── tests/          118 pytest tests, no infra required
├── RUNBOOK.md          keys, accounts, monthly costs for both systems
└── .github/workflows/ci.yml   4 jobs (see Testing below)
```

Two systems, deliberately **not** sharing code: they trade different
markets with different failure modes. What they share is philosophy
(paper-first, loss-inclusive ledgers, bounded self-tuning) and infra
patterns (FastAPI + asyncpg + Postgres, env-driven config, Docker Compose).

## Memecoin Tracker (repo root)

```
DEX Screener ──► discovery ─┐
                            ├─► signal engine ──► gates (enrich) ──► alert
Helius ──► wallets (+SOL) ──┘        │                                 │
PumpPortal ──► pump.fun feed         ▼                                 ▼
Binance Alpha ──► event watcher   wallet weights ◄── outcomes ◄── paper ledger
CoinGecko ──► BTC.D rotation
```

- **Stack**: FastAPI, asyncpg, PostgreSQL 16, aiohttp; single process,
  cooperative async workers started from `app/main.py`.
- **Feeds**: DEX Screener REST/WS (token discovery), Helius RPC + Enhanced
  Transactions API + optional Atlas WS/webhooks (wallet activity),
  PumpPortal WS (pump.fun launches/graduations), Binance Alpha token list +
  announcements, CoinGecko global (BTC dominance).
- **Wallet ingestion is mode-switched** (`WALLET_MODE`): `poll` is the
  default — outbound-only, free tier, no public URL needed; it walks
  `getSignaturesForAddress` and parses trades through Helius's Enhanced
  API, which correctly attributes vault-routed swaps that raw balance
  deltas miss. `webhook` and `ws` trade setup effort for latency.
- **Everything auditable over HTTP**: `/api/discovery`, `/api/signals`,
  `/api/wallets`, `/api/paper`, `/api/checks/{token}`, `/api/binance`,
  `/api/rotation`, `/api/graduations`, plus a single-file dashboard.

## Sentinel (`sentinel/`)

```
REGIME (5m) ──► may we trade at all?
SCOUT (15m) ──► ranked RS watchlist
ANALYST     ──► 4 setup detectors (range / breakout-retest / RS-mom / ICT)
CONVICTION  ──► rank + size the proposals (bounded)
RISK        ──► the veto: caps, breakers, governor
EXECUTOR    ──► paper (default) or live; mechanical exit ladder
COACH       ──► nightly/weekly: which setup×regime actually earns
```

- **Stack**: FastAPI + asyncpg + Redis (bus) + PostgreSQL, Next.js 14
  dashboard, pure-python indicators (no TA lib dependency — every formula
  is in the repo and unit-tested).
- **Event-sourced ledger**: every module publishes to Redis pub/sub and the
  bus archives append-only into Postgres (`events` + typed tables:
  regime snapshots, watchlists, proposals, decisions, trades,
  trade_events, halts, reports, config_versions). A trade row carries the
  **complete evidence snapshot** — indicator values, regime state, config
  version — captured at proposal time. Nothing is edited after the fact.
- **Dual ledger adapters**: `PgLedger` (live/paper) and `MemoryLedger`
  (backtest) implement the same interface, so the backtester replays
  klines through the *identical* live code path (`ReplayMarket` swaps the
  data feed, nothing else).
- **Config is versioned, not editable**: `config.yaml` is snapshotted with
  a content hash on boot; the dashboard shows history read-only.
- **Auth (v3.1)**: optional single-password sign-in — HMAC-signed expiring
  session cookie, stdlib only, off when `DASHBOARD_PASSWORD` is unset.
- **Notifications (v3.1)**: Discord/Telegram push on trade open/close,
  halts, coach reports, gate-open — plus an in-app Activity feed reading
  the persisted event bus.

## Dashboards

Both are deliberately **read-only**. The tracker ships a single-file HTML
dashboard on :8000; Sentinel a Next.js app on :3000 (server components
fetch the API with cookie forwarding, auto-refresh every 15 s). Sentinel's
pages: Live (regime, positions with SL→TP bars, watchlist, ICT map,
activity), Ledger (trades + evidence + risk vetoes), Performance
(scoreboard, equity curve, coach narratives), Config (versions).

## Testing & CI

Four GitHub Actions jobs on every push/PR:

1. **memecoin tracker** — compile + import smoke test of the FastAPI app.
2. **sentinel tests** — 118 pytest tests: indicators, every setup detector
   (fixture-built candles), regime classification, risk caps, executor
   ladder, all 8 live-gate lock combinations, conviction ranking/sizing,
   expectancy tuner, ICT concepts/pipeline, backtest determinism, auth
   token matrix, notify no-op.
3. **sentinel dashboard build** — `next build` must be clean.
4. **sentinel e2e** — real stack in CI: postgres service → `seed_demo.py`
   → uvicorn with auth on → built dashboard → 8 Playwright specs
   (sign-in flow, every page, API 401s, mobile-viewport overflow).
