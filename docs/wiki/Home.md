# crypto — the wiki

One repo, two trading systems, one philosophy: **prove the edge on paper
before a single real dollar moves, and let the ledger — not feelings —
decide what earns.**

| system | market | style | default state |
|---|---|---|---|
| [Memecoin Tracker](Tracker-Strategy.md) | Solana DEXes | follow vetted wallets into fresh tokens, gated hard | paper ledger |
| [Sentinel](Sentinel-Strategy.md) | Binance spot | rules-based intraday setups on ranked alts | paper, live gated 3× |

## Pages

- **[Architecture](Architecture.md)** — how the monorepo is built: modules,
  data flow, event sourcing, the dashboards, testing and CI.
- **[Tracker Strategy](Tracker-Strategy.md)** — the Solana side: discovery,
  rug gates, wallet curation (why PnL leaderboards are a trap), moonshot
  mode, Binance-event exit windows, BTC.D rotation.
- **[Sentinel Strategy](Sentinel-Strategy.md)** — the Binance side: regime
  filter, the four setups (incl. the full ICT sequence), the risk veto,
  the conviction engine, and the self-tuning loop.
- **[Operations](Operations.md)** — running it: modes, keys, sign-in,
  notifications, deployment options, the E2E suite.
- **[Build History](Build-History.md)** — how the system got here,
  version by version, including the mistakes that shaped it.

## The three rules everything obeys

1. **Losses are recorded, never hidden.** Both paper ledgers count rugs at
   −100%, include slippage and fees, and grey out *rejected* signals instead
   of deleting them. A ledger that can't embarrass you can't inform you.
2. **No discretionary overrides.** The dashboards are read-only. There is no
   "buy now" button, no martingale option, no way to widen a stop from the
   UI. Discipline that depends on willpower isn't discipline.
3. **Feedback loops are automatic and bounded.** Wallet weights (tracker)
   and setup trust (Sentinel) rise and fall with their own realized results,
   clamped to sane ranges — self-tuning without self-destruction.

> Costs, accounts and API keys for both systems live in
> [RUNBOOK.md](../../RUNBOOK.md) at the repo root.
