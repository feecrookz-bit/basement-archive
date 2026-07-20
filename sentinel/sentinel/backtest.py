"""Backtest harness — replays historical klines through the EXACT production
pipeline. ReplayMarket swaps in for LiveMarket and MemoryLedger for PgLedger;
regime.classify, scout scoring, the three analyst detectors, risk.evaluate,
and executor.step_trade are the very same functions the live workers call.
There is no parallel strategy implementation to drift.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from . import config as config_mod
from .bus import Bus
from .data.market import ReplayMarket
from .ledger import MemoryLedger
from .modules import analyst, regime, risk
from .modules.coach import build_report, metrics_from_trades
from .modules.executor import Executor

log = logging.getLogger("backtest")


async def replay(cfg, series: dict[tuple[str, str], list[dict]],
                 alt_symbol: str, equity: float = 10_000.0) -> dict:
    """Run the pipeline over the series; returns {ledger, summary}."""
    market = ReplayMarket(series)
    ledger = MemoryLedger()
    bus = Bus(redis=None, pool=None, persist=False)  # local-only bus
    executor = Executor(ledger, bus, cfg, mode="backtest")

    alt_1h = series[(alt_symbol, "1h")]
    entries_24h: list[int] = []  # ts_ms of entries, for the governor

    for i in range(60, len(alt_1h)):
        now_ms = alt_1h[i]["ts"]
        market.set_now_ms(now_ms)
        candle = alt_1h[i]

        # regime tick (same cadence as candles here: hourly >= 5min refresh)
        snap = await regime.tick(market, ledger, bus, cfg)

        # scout: minimal watchlist for the replayed symbol set (same scorer)
        from .modules import scout as scout_mod
        btc_closes = [c["close"] for c in await market.candles("BTC/USDT", "1h", 100)]
        alt_closes = [c["close"] for c in await market.candles(alt_symbol, "1h", 100)]
        score = scout_mod.rs_score(alt_closes, btc_closes, cfg) or 0
        entries = [{"pair": alt_symbol, "rs_score": score, "rank": 1,
                    "rs_decile": 10, "higher_lows_vs_btc": False,
                    "vol_24h_usd": 50_000_000, "spread_pct": 0.05,
                    "flags": {"unlock_blacklist": False,
                              "funding_extreme": False, "oi_loading": False}}]
        wl_id = await ledger.insert_watchlist(entries, 1, cfg.version_id)
        watchlist = {"id": wl_id, "entries": entries}

        proposals = await analyst.scan(market, ledger, bus, cfg, snap, watchlist)

        entries_24h = [t for t in entries_24h if now_ms - t < 86_400_000]
        open_positions = [{"pair": st.pair, "sector": risk.sector_of(st.pair, cfg),
                           "risk_quote": (st.entry - st.stop_initial) * st.initial_qty}
                          for st in executor.open.values()]
        state = risk.AccountState(equity=equity, open_positions=open_positions,
                                  entries_last_24h=len(entries_24h))
        for p in proposals:
            verdict = await risk.judge(p, state, ledger, bus, cfg)
            if verdict["decision"] == "accepted":
                await executor.on_accepted({"proposal": p,
                                            "sizing": verdict["sizing"]})
                entries_24h.append(now_ms)

        # price path within the candle: low then high then close, so stops
        # are honoured pessimistically before targets
        candles_ctx = await market.candles(alt_symbol, "1h", 24)
        for px in (candle["low"], candle["high"], candle["close"]):
            await executor.on_price(alt_symbol, px, candles_ctx)

    # summarize through the same coach math
    trades = _fold_trades(ledger)
    metrics, narrative = build_report(trades, _rejected(ledger), "backtest")
    return {"ledger": ledger, "metrics": metrics, "narrative": narrative}


def _fold_trades(ledger: MemoryLedger) -> list[dict]:
    out = []
    for t in ledger.trades:
        evs = [e for e in ledger.trade_events if e["trade_id"] == t["trade_id"]]
        closed = any(e["type"] in ("CLOSED", "STOP_HIT", "TRAIL_HIT",
                                   "HALT_FLATTENED") for e in evs)
        pnl = sum(-e["qty_delta"] * (e["price"] or 0) for e in evs
                  if e["qty_delta"] < 0) \
            - sum(e["qty_delta"] * (e["price"] or 0) for e in evs
                  if e["qty_delta"] > 0) \
            - sum(e["fees_quote"] for e in evs)
        rs = [e["r_at_event"] for e in evs if e["r_at_event"] is not None]
        out.append({"pair": t["pair"], "setup_type": t["setup_type"],
                    "regime_state": "backtest", "closed": closed,
                    "pnl_quote": pnl, "r_result": rs[-1] if rs else 0})
    return out


def _rejected(ledger: MemoryLedger) -> list[dict]:
    return [d for d in ledger.decisions if d["decision"] == "rejected"]


async def main(symbol: str, fixtures: str | None, days: int) -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = config_mod.load()
    if fixtures:
        series = {tuple(k.split("|")): v
                  for k, v in json.loads(open(fixtures).read()).items()}
    else:
        import aiohttp

        from .data.ingest import BinanceRest
        async with aiohttp.ClientSession() as sess:
            rest = BinanceRest(sess)
            series = {
                ("BTC/USDT", "1h"): await rest.klines("BTC/USDT", "1h", days * 24),
                ("BTC/USDT", "4h"): await rest.klines("BTC/USDT", "4h", days * 6),
                (symbol, "1h"): await rest.klines(symbol, "1h", days * 24),
            }
    result = await replay(cfg, series, symbol)
    print(json.dumps({"metrics": result["metrics"],
                      "narrative": result["narrative"]}, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main("SOL/USDT", None, 30))
