#!/usr/bin/env python3
"""Seed a Sentinel database with representative demo data through the real
PgLedger — used by the E2E suite and for dashboard previews.

Usage: DATABASE_URL=postgresql://... python scripts/seed_demo.py
Idempotent enough for CI (fresh DB each run); re-running on a seeded DB just
adds another batch.
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel import config as cfgmod  # noqa: E402
from sentinel import db  # noqa: E402
from sentinel.bus import Bus  # noqa: E402
from sentinel.ledger import PgLedger  # noqa: E402


async def main():
    pool = await db.init()
    cfg = cfgmod.load(Path(__file__).resolve().parent.parent / "config.yaml")
    await cfgmod.snapshot(pool, cfg)
    L = PgLedger(pool)
    bus = Bus(redis=None, pool=pool, persist=True)

    rid = await L.insert_regime({
        "btc_state": "TRENDING_UP_EARLY", "trading_allowed": True,
        "ema_structure": {}, "atr_percentile": 41.0, "realized_vol_24h": 0.02,
        "btc_move_1h_pct": 0.38, "kill_flags": [],
        "config_version_id": cfg.version_id})
    await bus.publish("regime", "regime.tick",
                      {"btc_state": "TRENDING_UP_EARLY", "trading_allowed": True})

    entries = [{"pair": "SOL/USDT", "rs_score": 3.4, "rank": 1, "rs_decile": 10,
                "higher_lows_vs_btc": True, "vol_24h_usd": 2.1e9,
                "spread_pct": 0.02,
                "flags": {"unlock_blacklist": False, "funding_extreme": False,
                          "oi_loading": True}},
               {"pair": "SUI/USDT", "rs_score": 2.6, "rank": 2, "rs_decile": 10,
                "higher_lows_vs_btc": True, "vol_24h_usd": 4.8e8,
                "spread_pct": 0.04,
                "flags": {"unlock_blacklist": False, "funding_extreme": False,
                          "oi_loading": False}}]
    wl = await L.insert_watchlist(entries, 320, cfg.version_id)
    await bus.publish("scout", "scout.watchlist", {"entries": entries})

    await L.insert_ict_snapshot(
        "SOL/USDT",
        {"current": "newyork",
         "asia": {"status": "closed", "high": 181.42, "low": 176.88,
                  "high_swept": False, "low_swept": True},
         "london": {"status": "closed", "high": 180.1, "low": 177.35,
                    "high_swept": True, "low_swept": False},
         "newyork": {"status": "open", "high": 179.8, "low": 177.9,
                     "high_swept": False, "low_swept": False}},
        {"pdh": 182.6, "pdl": 175.2, "pwh": 189.9, "pwl": 168.4,
         "pdh_hit": False, "pdl_hit": True, "pwh_hit": False, "pwl_hit": False},
        {"fvgs": [{"side": "bull", "low": 177.05, "high": 177.62, "idx": 41,
                   "filled": False}],
         "order_blocks": [{"side": "bull", "low": 176.9, "high": 177.3,
                           "idx": 38}]},
        cfg.version_id)

    async def trade(pair, setup, entry, stop, tgt, conv, agree, events,
                    reject=None):
        pid = await L.insert_proposal({
            "pair": pair, "setup_type": setup, "side": "long",
            "entry_price": entry, "stop_price": stop,
            "targets": [{"price": tgt,
                         "r_multiple": round((tgt - entry) / (entry - stop), 2)}],
            "evidence": {"conviction": conv, "agreeing_setups": agree,
                         "rr_first_target": round((tgt - entry) / (entry - stop), 2)},
            "regime_snapshot_id": rid, "watchlist_id": wl,
            "config_version_id": cfg.version_id})
        await bus.publish("analyst", "analyst.proposal",
                          {"pair": pair, "setup_type": setup})
        if reject:
            await L.insert_decision(pid, "rejected", reject, None)
            await bus.publish("risk", "risk.rejected",
                              {"proposal": {"pair": pair}, "reasons": reject})
            return
        risk_pct = 0.75 * min(1.5, max(0.8, conv / 1.5))
        sizing = {"qty": round(10000 * risk_pct / 100 / (entry - stop), 6),
                  "notional": 0, "risk_quote": round(10000 * risk_pct / 100, 2),
                  "risk_pct": round(risk_pct, 4), "equity_at_decision": 10000}
        await L.insert_decision(pid, "accepted", None, sizing)
        await bus.publish("risk", "risk.accepted",
                          {"proposal": {"pair": pair}, "sizing": sizing})
        tid = await L.open_trade(pid, pair, setup, "paper", cfg.version_id)
        await L.append_trade_event(tid, "OPENED", sizing["qty"], entry,
                                   entry * sizing["qty"] * 0.001, stop, 0.0,
                                   {"conviction": conv})
        await bus.publish("executor", "executor.opened",
                          {"trade_id": tid, "pair": pair, "mode": "paper"})
        for ev in events:
            await L.append_trade_event(tid, ev[0], ev[1], ev[2], 0, ev[3], ev[4])

    # open positions (conviction + confluence visible in the UI)
    await trade("SOL/USDT", "ict", 178.4, 176.8, 183.2, 4.38,
                ["ict", "rs_momentum"],
                [("PARTIAL_EXIT_TP1", -2.0, 181.2, 178.4, 1.5),
                 ("STOP_TO_BREAKEVEN", 0, None, 178.4, None)])
    await trade("SUI/USDT", "breakout_retest", 3.62, 3.47, 3.92, 2.8,
                ["breakout_retest", "range_play"], [])
    # closed history so setup_trust has signal
    for i in range(10):
        await trade(f"W{i}/USDT", "ict", 100, 95, 110, 1.9, ["ict"],
                    [("PARTIAL_EXIT_TP1", -5, 107, 95, 1.5),
                     ("TRAIL_HIT", -5, 111, 95, 2.1),
                     ("CLOSED", 0, 111, 95, 2.1)])
    for i in range(10):
        await trade(f"L{i}/USDT", "rs_momentum", 50, 48, 54, 1.0,
                    ["rs_momentum"],
                    [("STOP_HIT", -15, 47.9, 48, -1.05),
                     ("CLOSED", 0, 47.9, 48, -1.05)])
    # a rejected proposal for the veto table
    await trade("AVAX/USDT", "range_play", 29.5, 29.2, 31.0, 0.9,
                ["range_play"], [], reject=["sector_cap:L1"])

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for d in range(21):
        await pool.execute(
            "INSERT INTO equity_snapshots (mode, equity, ts) VALUES ('paper',$1,$2)",
            10000 + 300 * math.sin(d / 2.0) + 55 * d, base + timedelta(days=d))
    await L.insert_report(
        "daily", base + timedelta(days=19), base + timedelta(days=20),
        {"trades": 21, "win_rate": 52.4, "avg_r": 0.55, "profit_factor": 1.9,
         "net_pnl_quote": 402.1, "max_drawdown_quote": 120.0},
        "21 closed trades: 52.4% wins, avg +0.55R, net +402.10 USDT (PF 1.90). "
        "Best setup: ict. Rejections are the risk engine doing its job.")
    await L.insert_halt("daily", "imposed",
                        "daily equity -2.11% <= -2.0%; no new entries for 24h")
    print("seeded OK")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
