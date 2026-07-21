# Sentinel Strategy — Binance altcoin day-trading

Sentinel is a **discipline-enforcement machine, not a prediction engine**.
It executes a defined, rules-based intraday system on Binance spot with a
default state of *flat*. Weeks of no trades is a result, not a
malfunction.

## Layer 1 — Regime: may we trade at all?

A 5-minute BTC classifier (EMA structure + ATR percentile + realized vol)
answers one question before anything else runs. Alt longs are only
permitted in constructive BTC states; `VOLATILE_CHOP` or a sharp 1h BTC
move raises kill flags and the whole engine stands down. An opt-in
**rotation gate** additionally blocks alt longs when BTC dominance is
rising hard (money hiding up the quality curve).

## Layer 2 — Scout: where is relative strength?

Every 15 minutes, alts are ranked by RS vs BTC (multi-window return
spread), filtered by 24h volume and spread, flagged for token-unlock
blacklist / funding extremes / OI loading. Output: a small ranked
watchlist. Only top-decile-RS pairs with higher-lows-vs-BTC structure are
eligible for momentum entries.

## Layer 3 — Analyst: exactly four setups, long-only

- **Range play** — ≥3 touches each side over ≥48h; limit at range low +
  buffer; invalidation = close below range low; target = range high.
- **Breakout-retest** — multi-day resistance broken on ≥2× volume, then a
  retest that holds (1h close above the level). **The breakout candle
  itself is never bought** — hard invariant, pinned by a test.
- **RS momentum** — top-decile RS, uptrend structure, pullback to the 1h
  20 EMA with stochRSI reset, entry on reclaim; invalidation = structure
  low.
- **ICT sequence** (15m, config-gated) — every stage mandatory, in order:
  1. **Liquidity sweep** of a key low (session low / PDL / equal-lows
     pool): wick below + close back above. A *close* below is a
     breakdown, not a sweep.
  2. **Displacement** up leaving a fresh bullish Fair Value Gap.
  3. **MSS** — close above the pre-sweep swing high confirms the shift.
  4. Entry **only on the retrace** into FVG ∩ OTE (62–79% of the
     displacement leg) or the displacement's order block — never the
     displacement candle itself.
  - Stop below the sweep low; target = nearest resting buy-side liquidity
    (session high / PDH / PWH); R:R floor enforced. SMT divergence vs BTC
    recorded as confluence evidence.

Exits are mechanical for all setups: **50% off at 1.5R + stop to
breakeven, 25% at 2.5R, remainder trailed on the 1h swing low.** The
dashboard has no override buttons on purpose.

## Layer 4 — Conviction: edge quality, not aggression

Between Analyst and Risk sits the v3 conviction engine. For each pair,
`conviction = Σ(base_weight × ledger_trust)` over agreeing setups, with a
**confluence bonus** (independent setups agreeing on one pair) and an
**ICT premium** (highest base weight). It does exactly two things:

1. **Ranking** — proposals are judged best-first, so the limited slots
   and open-risk budget go to the strongest opportunities.
2. **Bounded sizing** — risk scales 0.8×–1.5× of base with conviction
   (top trade ≈ 1.1% vs 0.75% base). Every hard cap still vetoes.

**Ledger trust** is the self-tuning half: each setup is weighted by its
own trailing realized expectancy (avg R over a window), cold-start
neutral, clamped — winners rise, losers fade and get gated out. The
dashboard's *Setup trust* panel shows the current weights.

## Layer 5 — Risk: the veto

- size = equity × 0.75% ÷ (entry − stop). **Stop distance determines
  size, never the reverse.**
- max 3 concurrent positions · max 2% total open risk · 1 per sector
- daily −2% → flatten everything, 24h entry halt (logged)
- weekly −5% → halt until a typed justification is stored forever
- overtrading governor: max 4 new entries per 24h
- **No martingale, no averaging down, no doubling after losses. Not
  configurable.**

## The paper → live gate

Live trading requires three independent locks, all open:

1. `mode.live: true` in config
2. the CLI flag `--confirm-live-i-accept-losses`
3. **≥ 30 distinct days of logged paper trades**, computed from the ledger
   itself (`v_paper_readiness`) — cannot be faked by editing config

Anything less silently runs paper. Enforced in code, covered by a test of
all 8 lock combinations.

## The Coach: closing the loop

Nightly/weekly reports break results down by **setup × regime × pair** —
which combinations actually earn — with a plain-language narrative pushed
to Discord/Telegram. The backtester replays history through the *same*
functions the live workers call (swapped data feed + memory ledger, no
parallel implementation), with within-candle paths applied
pessimistically (low before high — stops honoured before targets).

## Honest limitations

The system enforces discipline on a defined strategy; **it does not
guarantee the strategy is profitable** — that's what the 30-day paper
period and the Coach exist to determine. Paper fills are a model; real
fills are worse in fast markets. Backtest ≥ paper ≥ live, in that order
of optimism. Believe the ledger over your feelings.
