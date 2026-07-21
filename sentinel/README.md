# Sentinel — transparency-first altcoin day-trading engine

A discipline-enforcement machine, not a prediction engine. Sentinel executes
a defined, rules-based intraday system on Binance spot — regime filtering,
three setups, mechanical risk management — with full auditability and a
default state of **flat**. It ships in **paper mode** and makes going live
deliberately hard.

```
REGIME (5m) ──► may we trade at all?
SCOUT (15m) ──► ranked RS watchlist (volume/spread filter, unlock blacklist)
ANALYST     ──► exactly 3 setups: range / breakout-retest / RS momentum
RISK        ──► the veto: sizing, caps, breakers, governor
EXECUTOR    ──► paper (default) or live; mechanical exit ladder only
COACH       ──► nightly/weekly: which setup×regime actually earns
```

All module chatter goes over Redis pub/sub and is archived append-only in
Postgres (`events` + typed tables). Every trade stores the complete evidence
snapshot (indicator values, regime state, config version) that produced it.

Accounts, keys, and running costs for this and the memecoin tracker:
[../RUNBOOK.md](../RUNBOOK.md).

## Run (paper — no keys needed)

```bash
cp .env.example .env
docker compose up --build
# dashboard: http://localhost:3000   api: http://localhost:8080
```

Paper mode uses live public Binance market data with simulated fills
(0.1% taker fee + spread/impact slippage model). No API keys required.

## The paper → live gate

Live trading requires **three independent locks**, all open:

1. `mode.live: true` in `config.yaml`
2. the CLI flag: `python -m sentinel run --confirm-live-i-accept-losses`
3. ≥ 30 distinct days of logged paper trades — computed from the ledger
   itself (`v_paper_readiness`), so it cannot be faked by editing config

Anything less silently runs paper. This is enforced in code
(`executor.resolve_mode`) and covered by a test of all 8 lock combinations.

## Risk rules (the veto)

- size = equity × 0.75% ÷ (entry − stop). **The stop distance determines
  size — never the reverse.**
- max 3 concurrent positions · max 2% total open risk · 1 position per
  sector (config sector map)
- daily −2% → flatten everything, 24h entry halt (logged)
- weekly −5% → halt until `python -m sentinel resume --reason "..."` with a
  typed justification, stored forever
- overtrading governor: max 4 new entries per 24h
- **No martingale, no averaging down, no doubling after losses.** Not
  configurable. Requests to add them will be refused.

## Setups (three momentum-family + the ICT class)

> v2 amendment: the original spec said "exactly three setups". The ICT
> agent below was added deliberately as a config-gated fourth class
> (`ict.enabled`) — it changes nothing about the pipeline: same Risk
> veto, same paper ledger, and the Coach measures it against the other
> three. If its ledger section stays red, disable it in config.

- **Range play** — ≥3 touches each side over ≥48h; limit at range low +
  buffer; invalidation = close below range low; target = range high.
- **Breakout-retest** — multi-day resistance broken on ≥2× volume, then a
  retest that holds (1h close above the level). **The breakout candle itself
  is never bought** — hard invariant, enforced in code, pinned by a test.
- **RS momentum** — top-decile RS pair, uptrend structure, pullback to 1h
  20 EMA with stochRSI reset, entry on reclaim; invalidation = structure low.

- **ICT agent** (15m) — the full bullish ICT sequence, every stage
  mandatory: sell-side **liquidity sweep** of a key low (session low, PDL,
  or equal-lows pool; wick below + close back above — a close below is a
  breakdown, not a sweep), **displacement** up leaving a fresh bullish
  FVG, **MSS** confirm (close above the pre-sweep swing high), then entry
  only on the **retrace into FVG ∩ OTE (62–79%)** or the displacement's
  order block — never the displacement candle itself. Stop below the
  sweep low; target = nearest resting buy-side liquidity (session high /
  PDH / PWH); R:R floor `ict.min_rr`. SMT divergence vs BTC is recorded
  as confluence evidence. Long-only, like everything here. The dashboard
  shows the ICT map: sessions with swept flags, PDH/PDL hits, and fresh
  FVG/OB zones.

Exits are mechanical for all setups: 50% off at 1.5R and stop to
breakeven, 25% at 2.5R, remainder trailed on the 1h swing low. The
dashboard has no override buttons on purpose.

## Conviction engine (v3 — edge quality, not aggression)

Between the Analyst and the Risk veto sits a conviction layer that decides
*which* trades to take and *how much* to size them — within the unchanged
risk envelope. It answers the problem that the 3 position slots used to go
to whichever proposal was seen first, not the best one.

For each pair with any setups firing, conviction =
`Σ(base_weight × ledger_trust)` over the agreeing setups, boosted by a
**confluence bonus** (multiple setups on one pair) and an **ICT premium**
(ICT carries the highest base weight). Three sources, all the operator
asked for:

- **Confluence** — more independent setups agreeing = higher conviction.
- **ICT premium** — the ICT sequence is treated as the premium signal.
- **The ledger decides** — each setup is weighted by its own trailing
  realized expectancy (avg R over the last `window_trades`). Cold-start
  neutral (1.00×) below `min_trades`, then winners rise toward the clamp
  ceiling and losers fade to the floor and get gated out. Self-tuning,
  bounded, automatic — the same philosophy as the tracker's wallet weights.

Conviction then does two things, neither of which loosens risk:
1. **Ranking** — proposals are judged best-conviction-first, so the limited
   slots and the 2% open-risk budget go to the strongest opportunities.
   One deliberately-chosen trade per pair replaces the old arbitrary
   `already_in_pair` rejection.
2. **Sizing** — risk-per-trade scales with conviction, *bounded*
   (`min_mult`–`max_mult`, default 0.8–1.5×, so a top trade risks ~1.1% vs
   the 0.75% base). **Every hard cap still vetoes** — 2% total open risk,
   3 concurrent, sector cap, both circuit breakers. Average risk stays
   disciplined; only selection and modest sizing improve. That's edge
   quality, not leverage.

The dashboard shows a conviction chip + confluence count on each position
and a **Setup trust** panel (what the ledger currently thinks of each
setup). A secondary, opt-in **rotation gate** (`regime.rotation.enabled`,
default off) blocks alt longs when BTC dominance is rising hard.

## Backtest

```bash
python -m sentinel backtest --symbol SOL/USDT --days 30
```

The harness replays klines through the **same functions** the live workers
call (`regime.classify`, the analyst detectors, `risk.evaluate`,
`executor.step_trade`) — a swapped data feed (`ReplayMarket`) and ledger
adapter (`MemoryLedger`), not a parallel implementation. Within-candle price
paths are applied pessimistically (low before high), so stops are honoured
before targets.

## Development

```bash
pip install -r requirements.txt
pytest -q          # 62 tests, no infra needed
```

## LIMITATIONS — read this before trusting it

This system **enforces discipline on a defined strategy; it does not
guarantee the strategy is profitable.** That is what the 30-day paper period
and the Coach analytics exist to determine — run it, read the weekly
setup×regime breakdown, and believe the ledger over your feelings.

Other honest caveats:

- Paper fills are a model (spread + impact + taker fee). Real fills are
  worse in fast markets; treat paper results as an upper bound.
- The three setups are simple technical patterns. In regimes where they have
  no edge, the correct output of this system is *no trades and no PnL* —
  weeks of flat is a result, not a malfunction.
- Backtests share the live code path but not live reality: no funding for
  spot, but also no outages, partial fills, or bans. Backtest ≥ paper ≥
  live, in that order of optimism.
- The unlock calendar ships as a manual CSV stub. An empty calendar means
  that guard is OFF — wire a real source before trusting it.
- Regime and RS math are as good as Binance's public data and your uptime.
  The engine fails safe (flat) on missing data, but flat has opportunity
  cost too.
- Day-trading altcoins is a negative-sum game after fees for most
  participants. The most valuable output of this machine may be a ledger
  that proves you shouldn't be doing it.
