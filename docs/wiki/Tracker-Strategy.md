# Tracker Strategy — Solana memecoins

The tracker's thesis: **you cannot out-research a memecoin, but you can
follow people who are consistently early — if you filter out the rugs and
honestly measure whether following them earns.**

## The signal path

A tracked wallet **buy** becomes an alert only if ALL of these hold:

1. **Freshness** — token first seen by discovery within `FRESH_HOURS`.
2. **Size** — buy ≥ `MIN_BUY_SOL` (dust buys are noise/spam).
3. **Safety gates** (cached 10 min, every result auditable at
   `/api/checks/{token}`):
   - liquidity ≥ `MIN_LIQUIDITY_USD`, 1h volume ≥ `MIN_VOLUME_H1_USD`
   - FDV ≤ `MAX_FDV_USD` — already-mooned means the edge is gone
   - mint authority revoked — else supply can be inflated on you
   - freeze authority revoked — else honeypot: you can buy, not sell
   - top-10 holders ≤ `MAX_TOP10_PCT`% — else you're exit liquidity
4. **Score** ≥ `MIN_SIGNAL_SCORE`:
   `Σ(wallet_weight × conviction) × confluence × freshness` — conviction
   grows with log of SOL size; confluence multiplies when several distinct
   wallets buy within 30 min; wallet_weight is auto-tuned 0.25–3.0 by
   track record.

**Method-3 gates** (momentum path only) automate the 60-second checklist:
h1 buy/sell ratio, 5-minute volume still printing, optional holder-count
growth. Missing data never gates — they tighten when data exists.

Failed signals are recorded greyed-out (`gated=false`), never silently
dropped. **Exit alerts**: any tracked wallet *selling* a token we
signalled pings immediately — smart money leaving is the signal to leave.

## The paper ledger is the verdict

Every gated signal opens a hypothetical position; a monitor re-prices
every minute and closes at TP / SL / timeout — or **dead** (pair vanished
= rug, −100%, recorded as such). PnL is net of assumed slippage. Outcomes
push the trigger wallet's weight up or down, **so losers mute
themselves**. Run 2–4 weeks: if the ledger isn't green *including* losses
and slippage, the wallet list isn't good enough yet — which is the answer
working as intended, at zero cost.

## Wallet curation (this IS the product)

The hard-won lesson of this build: **PnL leaderboards are a trap.**
On-chain vetting (`scripts/vet_wallets.py`, findings in
[WALLETS.md](../WALLETS.md)) showed the top Solana "profit" wallets are
almost all high-frequency bots — hundreds to thousands of sub-minute
trades a day that no follower system can shadow; by the time you see the
buy, they've sold.

What works: **accumulators** — a few trades a day, holds measured in
minutes-to-hours, found by analyzing *who bought runner tokens early and
held*. Defenses built in:

- `app/wallet_quality.py` re-vets every tracked wallet on a schedule and
  **auto-mutes bots** (weight → 0.25 floor), classification shown on
  `/api/wallets`.
- Bundle detection mindset: wallets that always buy in the same block are
  one operator, not five — confluence from them is fake.
- Prune ruthlessly; deleting a dead wallet beats muting it.

## Moonshot mode (low-MC 100× hunting)

A second signal class, opposite in shape to momentum — moonshots want
quiet **accumulation**, not heat:

- FDV band $50k–$1.5M (100× from $1.5M is $150M — rare but real; 100×
  from $50M is fantasy) with liquidity ≥ 8% of FDV *and* ≥ $10k.
- Trigger = ≥3 tracked-wallet buys of ≥0.25 SOL across a 7-day window with
  ≥12h first-to-last span. Three buys in one block is a bundle, not
  conviction — it won't fire.
- Paper exits are survival-shaped: **no take-profit** (that's how you 2×
  your way out of a 100×), SL −60%, 30-day horizon, `peak_x` records the
  max multiple reached.

**Base rates, honestly**: at this cap the modal outcome is −100%. A
moonshot book only works as a portfolio — many small identical tickets
where one 40× pays for thirty corpses. Expect the momentum ledger to look
better for months while the moonshot ledger looks terrible right up until
it doesn't.

## Exit-window intelligence

- **Binance events**: a watcher polls Binance Alpha's token list and the
  announcements feed. A Binance touchpoint on a token we discovered,
  signalled or hold is historically the best exit-liquidity window a
  low-cap ever gets — the alert says *"consider securing profits"*, not
  "buy" (listing pumps are sell-the-news). Launchpool / HODLer-airdrop
  announcements alert unconditionally — rare passive-capital windows.
  Delistings of tracked tokens alert with exit-now framing.
- **Graduation plays**: PumpPortal's WS seeds pump.fun launches into
  discovery and records Raydium/PumpSwap migrations — the graduation
  moment is a known liquidity/attention event.
- **Rotation overlay**: hourly BTC-dominance read → `RISK_OFF` (BTC.D
  rising — long tail bleeds) / `ALT_ROTATION` (BTC.D falling — the
  alt-season tell) / `NEUTRAL`. Alerts only on regime *changes*. Data,
  never a trade — and the long tail going vertical is itself the classic
  cycle-top signal.
