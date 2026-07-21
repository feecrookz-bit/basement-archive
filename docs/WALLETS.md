# Curating the wallet list — the actual product

The tracker is only as good as the wallets in `tracked_wallets`. This note
records what on-chain research (July 2026, via `scripts/vet_wallets.py` and
your own Helius key) found, and how the system now defends against it.

## The finding: leaderboard wallets are un-shadowable

Every wallet on the public **Kolscan PnL leaderboard** — the obvious place
a beginner starts — turned out to be a **high-frequency bot** when vetted
on-chain:

| Wallet (rank) | Trades/day | Median hold | Verdict |
|---|---:|---:|---|
| Cented (#17) | ~2,000,000 | seconds | HFT bot |
| Cupsey (#42) | thousands | seconds | HFT bot |
| Zuki (#2) | 1,876 | 0.4 min | bot |
| King (#18) | 839 | 0.4 min | bot |
| Sebastian (#6) | 181 | 0.1 min | bot |

Not one scored a `TRACK` verdict. The reason is structural, not bad luck:
**the leaderboard ranks by realized PnL, and on Solana the PnL leaders are
bots** that fire hundreds–thousands of sub-minute trades a day. A follower
system — webhook *or* poll — cannot shadow a 20-second hold: the position
is gone before your alert fires. Copy them and you are exit liquidity.

This is the empirical version of the README's warning. **Famous ≠
followable.** PnL is the wrong first filter.

## What you actually want: accumulators

The trackable archetype is the opposite of a leaderboard bot: a wallet that
**buys and holds for hours to days**, with a handful of trades per day, not
hundreds. These rarely top *daily* PnL boards (churn wins those) but they
are the only wallets a follower can mirror — and they line up exactly with
the moonshot / accumulation philosophy in `app/moonshot.py`.

Sources worth mining for them (verify each on-chain before adding):
- **GMGN / Cielo / Birdeye** "smart money" tabs, then sort by *hold time*,
  not PnL, and demand 30+ days of history.
- **Early-buyer analysis** on a token that already ran: pull its early
  holders, find the ones that *held through* the run, check they do it
  repeatedly across different tokens.
- Filter targets (per research): 40–60% win rate (realistic, not
  outlier-carried), 50+ trades over weeks, **median hold measured in
  minutes-to-hours, not seconds**, and original entries (not a copy of
  another wallet).

## The tools

### `scripts/vet_wallets.py` — vet before you add
On-chain scorer using only free Helius endpoints. Scores each candidate on
what matters to a *follower*: alive, sane cadence, shadowable hold time,
flip rate. Rejects HFT bots outright.

```bash
HELIUS_API_KEY=... python scripts/vet_wallets.py \
  "name:ADDRESS" "name2:ADDRESS2"
# or: --file candidates.txt   (lines of  label:address)
```
Verdicts: `TRACK` (add it), `MAYBE` (watch), `SKIP`/`HFT_BOT`/`DEAD` (don't).
It prints a paste-ready JSON array of the TRACK wallets for `/api/wallets`.

### `app/wallet_quality.py` — auto-defence in the live system
Even vetted wallets drift (a trader flips to botting, or you added one in
haste). Every `WALLET_QUALITY_INTERVAL_HOURS` the tracker re-measures every
tracked wallet's cadence and classifies it `bot` / `accumulator` / `normal`.
**Bots are auto-muted** — weight pinned to the 0.25 floor so their buys can
never clear `MIN_SIGNAL_SCORE` alone — while accumulators keep full weight.
It classifies and mutes; it never deletes (pruning stays your call) and
never touches win/loss counters. Classification shows on `/api/wallets`.

## Discipline

- **Prune ruthlessly.** The weight/mute mechanics help, but deleting a dead
  wallet beats muting it. Review `/api/paper` every couple of weeks.
- **Beware bundles.** Confluence from wallets that always buy in the same
  block is one operator, not five — the confluence multiplier is fooled by
  it. Prefer wallets that enter *independently*.
- **The list is the product.** No amount of engineering downstream fixes a
  bad wallet list. This is where your edge, if any, actually lives.
