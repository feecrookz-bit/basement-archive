# Build History

How this repo went from an archived backend to a two-system trading
operation — including the wrong turns, because they shaped the design.

## v1 — Memecoin Tracker (from the handover spec)

Repo repurposed; the tracker built to a written spec: DEX Screener
discovery, Helius wallet tracking, the five rug gates, weighted signal
scoring, and the loss-inclusive paper ledger. The core stance was set
here: **no signal without gates, no gate result hidden, no PnL claim
without counting rugs at −100%.** Moonshot mode added as a second,
accumulation-shaped signal class with survival-shaped exits.

## v2.2 – v2.3 — exit-window intelligence

Research question: "how do we secure profits from coins that run?"
Answers shipped as watchers, not predictions:

- **Binance events** — Alpha list + announcements polling; classified
  `listing` / `delisting` / `launchpool` / `hodler_airdrop`. Listings on
  held tokens = the historical best exit-liquidity window.
- **Method-3 gates** — the manual 60-second momentum checklist automated
  (buy/sell ratio, current m5 volume, holder growth).
- **pump.fun graduation watcher** (PumpPortal WS) and the **BTC.D
  rotation overlay** (RISK_OFF / ALT_ROTATION / NEUTRAL).

## Sentinel v1 — the discipline engine

The Binance side built as its own system under `sentinel/`: five modules
over an event-sourced Postgres ledger, three long-only setups, the
mechanical exit ladder, hard risk caps with circuit breakers, and the
**triple paper→live gate** (config + CLI flag + 30 ledger-proven paper
days). Backtester shares the live code path via swapped adapters.
Dashboard restyled to the FATBot dark/amber design reference.

## Sentinel v2 — the ICT agent

A fourth, config-gated setup class implementing the full bullish ICT
sequence (sweep → displacement/FVG → MSS → OTE retrace entry), with
sessions/PDH/PDL tracking, SMT divergence evidence, and its own dashboard
map. Same risk veto, same ledger; the Coach measures it against the other
three, and if its section stays red, it gets disabled in config.

## The wallet reckoning

The single most valuable research result in the repo: vetting the
"obvious" wallets from Solana PnL leaderboards revealed **every one was a
high-frequency bot** — un-shadowable by any follower system. Response:

- `scripts/vet_wallets.py` — on-chain vetting before any wallet is added
  (trade frequency, hold times, bundle detection).
- `app/wallet_quality.py` — scheduled re-vetting that **auto-mutes bots**
  (weight → 0.25 floor). The system now defends itself against its own
  wallet list.
- Six **accumulator** wallets found by holder-analysis of runner tokens
  replaced the leaderboard names. Findings in [WALLETS.md](../WALLETS.md).

## Sentinel v3 — the conviction engine

"Maximize the Binance strategy" answered with **edge quality, not
leverage**: proposals ranked by conviction (setup confluence × ledger
trust × ICT premium), sizing scaled within 0.8–1.5× bounds, and
**expectancy self-tuning** — each setup's conviction weight tracks its
own trailing realized R, so the ledger continuously reallocates capital
toward what's actually working. Every hard risk cap unchanged.

## Sentinel v3.1 — the product layer

Sign-in (single-password HMAC sessions, off by default), Discord/Telegram
notifications on the moments that matter, a live-updating dashboard with
an Activity feed off the event bus, `seed_demo.py`, and an 8-spec
Playwright E2E suite running the full stack (postgres → seeded API with
auth → built dashboard) as a fourth CI job. 118 unit tests green.

## Infrastructure milestones

- Monorepo consolidation (one repo, two systems), 4-job CI, devcontainer.
- `deploy/` — VPS bootstrap script + cloudflared tunnel compose for 24/7
  hosting off Codespaces.
- `WALLET_MODE=poll` — free-tier wallet tracking with **no public URL**,
  rerouted through Helius Enhanced Transactions after raw balance-delta
  parsing proved blind to vault-routed swaps.
