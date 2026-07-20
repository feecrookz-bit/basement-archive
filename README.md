# Memecoin Tracker v2 — gated signals + proof-of-edge ledger

Discovery (DEX Screener) × wallet tracking (Helius/Solana), with the three
layers that separate a working operation from a toy: **rug gates**, **wallet
quality weighting**, and a **loss-inclusive paper ledger**.

```
DEX Screener ──► discovery ─┐
                            ├─► signal engine ──► gates (enrich) ──► alert
Helius ──► wallets (+SOL) ──┘        │                                 │
                                     ▼                                 ▼
                          wallet weights ◄── outcomes ◄── paper ledger
```

## Run
```bash
cp .env.example .env      # add HELIUS_API_KEY
docker compose up --build # dashboard: http://localhost:8000
```

## The signal path (what fires and why)
A tracked wallet **buy** only becomes an alert if ALL of these hold:

1. Token is *fresh* — first seen by discovery within `FRESH_HOURS`.
2. Buy ≥ `MIN_BUY_SOL` (dust buys are noise/spam).
3. **Safety gates** pass (cached 10 min, auditable at `/api/checks/{token}`):
   - liquidity ≥ `MIN_LIQUIDITY_USD` and 1h volume ≥ `MIN_VOLUME_H1_USD`
   - FDV ≤ `MAX_FDV_USD` (already-mooned = your edge is gone)
   - mint authority revoked (else supply can be inflated on you)
   - freeze authority revoked (else honeypot: you can buy, not sell)
   - top-10 holders ≤ `MAX_TOP10_PCT`% of supply (else you're exit liquidity)
4. Score ≥ `MIN_SIGNAL_SCORE`, where score =
   Σ (wallet_weight × conviction) × confluence × freshness
   - *conviction* grows with log of SOL size (10 SOL buy ≫ 0.6 SOL buy)
   - *confluence*: several distinct wallets within 30 min multiplies score
   - *wallet_weight* is auto-tuned 0.25–3.0 by that wallet's track record

Failed signals are still recorded (`gated=false`, greyed on the dashboard)
so you can audit the filter and tune thresholds — never silently dropped.

**Exit alerts:** any tracked wallet *selling* a token we signalled pings you
immediately. Smart money leaving is the signal to leave.

## Paper ledger (`/api/paper`)
Every gated signal opens a hypothetical `PAPER_STAKE_SOL` position at the
checked price. A monitor re-prices every minute and closes at
+`PAPER_TP_PCT`% / −`PAPER_SL_PCT`% / `PAPER_TIMEOUT_HOURS`h, or **dead**
(pair vanished → −100%, i.e. a rug, recorded as such). PnL is net of
`ASSUMED_SLIPPAGE_PCT` round-trip. Outcomes push the trigger wallet's weight
up or down, so losers mute themselves.

Run it for 2–4 weeks. If the ledger isn't green **including** losses and
slippage, the wallet list isn't good enough yet — that's the answer working
as intended, and it cost nothing.

## Curating the wallet list (this IS the product)
The system is only as good as the wallets in `tracked_wallets`. Sources the
experienced crowd uses: top-trader tabs on Birdeye/GMGN for tokens that
already ran, then verify each wallet's history yourself before adding.
Prune ruthlessly — the weight mechanism helps, but deleting beats muting.
Beware *bundled* wallets (one operator, many addresses): confluence from
wallets that always buy within the same block is one buyer, not five.

## Modes
- `DISCOVERY_MODE`: `poll` (official REST, default) | `ws` (spoofed-origin socket)
- `WALLET_MODE`: `ws` (Helius Atlas, paid plan) | `webhook` (free tier, needs
  public URL → `/webhooks/helius`) | `off`

## API
`/api/discovery` · `/api/signals` · `/api/wallets` (POST/DELETE to manage) ·
`/api/paper` (ledger + summary) · `/api/checks/{token}?force=true`

## Moonshot mode (low-MC 100x hunting)
A second signal class, opposite in shape to momentum. Momentum wants heat;
moonshots want quiet **accumulation** on tokens with room to run:

- FDV band **$50k–$1.5M** (`MOONSHOT_MIN/MAX_FDV`) — 100x from $1.5M is
  $150M, rare but real; 100x from $50M is fantasy.
- Liquidity as a **ratio**: liq ≥ 8% of FDV *and* ≥ $10k. Thin liq relative
  to mcap is the slow-rug shape.
- Trigger = **accumulation pattern**, not a burst: ≥3 tracked-wallet buys of
  ≥0.25 SOL inside a 7-day window, with first-to-last span ≥12h. Three buys
  in one block is a bundle, not conviction — it won't fire.
- Discovery window is 7 days (`MOONSHOT_FRESH_HOURS=168`), because these
  setups form after the listing hype, not during it.
- Paper exits are survival-shaped: **no take-profit** (that's how you 2x your
  way out of a 100x), SL −60%, 30-day horizon, and `peak_x` records the max
  multiple reached — so the ledger tells you what letting winners run would
  actually have earned, including all the ones that died.

Moonshot signals show with 🌙 on the dashboard; `/api/paper` splits the
summary by kind.

**Base rates, honestly:** at this market cap the modal outcome is −100%.
A moonshot book only works as a portfolio — many small, identical tickets
where one 40x pays for thirty corpses — and the `moonshot` ledger section
exists to tell you whether *your wallet list* finds those 40x's often
enough. Expect the momentum ledger to look better for months while the
moonshot ledger looks terrible right up until it doesn't.

## Method-3 gates (v2.2)
The momentum path now also automates the "60-second checklist": h1 buy/sell
transaction ratio ≥ `M3_MIN_BUY_SELL_RATIO_H1`, 5-minute volume still
printing (≥ `M3_MIN_VOLUME_M5_USD` — momentum must be *current*, not
historical), and optional holder-count growth between checks
(`M3_REQUIRE_HOLDER_GROWTH`, counted via Helius DAS up to
`HOLDER_COUNT_MAX_PAGES`×1000 accounts). Missing data never gates — these
tighten the filter when the data exists, and every rejection lands in
`fail_reasons` like the rest. Moonshot gates are unchanged: heat filters
would contradict quiet accumulation.

## Binance events (v2.2)
A watcher polls Binance Alpha's public token list and (best-effort) the
listing-announcements feed, and alerts when a token we discovered,
signalled, or hold in the paper ledger gets a Binance touchpoint —
historically the single best exit-liquidity window a low-cap ever gets.
The alert says "consider securing profits", not "buy": listing pumps are
classically sell-the-news, and distribution follows the spike. Events are
recorded in `binance_events` (`/api/binance`). This flags exit windows;
it does not predict them.

## Graduation plays (v2.2)
PumpPortal's free WebSocket seeds pump.fun launches into discovery
(`source='pumpfun'`) and records migrations to Raydium/PumpSwap in
`graduations` (`/api/graduations`). The tradeable pattern is the
post-graduation **dump → reclaim**: early curve buyers dump into new
liquidity (−30–60% is normal), and if price then reclaims the graduation
level after a ≥ `GRAD_MIN_DUMP_PCT`% flush inside
`GRAD_RECLAIM_WINDOW_HOURS`, a 🎓 `kind='graduation'` signal fires — still
through the standard safety gates — and opens a paper trade with
momentum-style exits. Tokens that never reclaim were nothing and cost
nothing; the ledger's graduation section tells you whether the reclaim
entry actually earns.

## Honest footnote
This is a candidate-surfacing and measurement system, not an income machine.
Copy-trading meme wallets is a negative-sum game where most participants
lose; the sustainable edge, if any, is in wallet curation + discipline, and
the ledger exists precisely so you find out cheaply whether you have one.
