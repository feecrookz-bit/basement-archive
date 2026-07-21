"""
Wallet quality classifier — self-defence against un-shadowable wallets.

Research finding (see docs/WALLETS.md): the wallets that top Solana PnL
leaderboards are almost all high-frequency bots — hundreds to thousands of
trades per day with sub-minute holds. A follower system cannot shadow them:
the position is gone before any alert (webhook or poll) fires. Copy them and
you are pure exit liquidity.

This worker periodically measures each tracked wallet's on-chain cadence and
classifies it:

  * bot         — trades/day above the cap OR median gap below the floor.
                  Auto-muted: weight pinned to the 0.25 floor so its buys
                  can never clear MIN_SIGNAL_SCORE alone.
  * accumulator — low cadence, long gaps: buys and holds. The tracker's
                  ideal source (see moonshot.py). Left at full weight.
  * normal      — in between; left to the paper-ledger weight tuning.

It only *classifies and mutes*; it never deletes (pruning stays your call)
and never touches a wallet's win/loss counters. Config-gated
(WALLET_QUALITY_ENABLED) and safe to disable.
"""
import asyncio
import logging
import statistics
from datetime import datetime, timezone

import aiohttp

from . import config, db

log = logging.getLogger("wallet_quality")

BOT = "bot"
ACCUMULATOR = "accumulator"
NORMAL = "normal"
UNKNOWN = "unknown"


def classify(trades_per_day: float | None, median_gap_min: float | None,
             sampled: int, cfg=config) -> str:
    """Pure classifier from cadence metrics."""
    if trades_per_day is None or median_gap_min is None or sampled < 5:
        return UNKNOWN
    if (trades_per_day > cfg.WALLET_MAX_TRADES_PER_DAY
            or median_gap_min < cfg.WALLET_MIN_HOLD_MIN):
        return BOT
    if (trades_per_day <= cfg.WALLET_ACCUMULATOR_MAX_TPD
            and median_gap_min >= cfg.WALLET_ACCUMULATOR_MIN_GAP_MIN):
        return ACCUMULATOR
    return NORMAL


async def _metrics(sess, addr: str) -> dict:
    url = f"{config.HELIUS_RPC_URL}/?api-key={config.HELIUS_API_KEY}"
    async with sess.post(url, json={"jsonrpc": "2.0", "id": 1,
                                    "method": "getSignaturesForAddress",
                                    "params": [addr, {"limit": 200}]},
                         timeout=30) as r:
        res = ((await r.json(content_type=None)) or {}).get("result") or []
    times = sorted(s["blockTime"] for s in res
                   if not s.get("err") and s.get("blockTime"))
    if len(times) < 5:
        return {"trades_per_day": None, "median_gap_min": None,
                "sampled": len(times)}
    span_days = max((times[-1] - times[0]) / 86400, 1e-6)
    gaps = [b - a for a, b in zip(times, times[1:])]
    return {"trades_per_day": round(len(times) / span_days, 2),
            "median_gap_min": round(statistics.median(gaps) / 60, 2),
            "sampled": len(times)}


async def classify_all() -> None:
    if not config.HELIUS_API_KEY:
        log.warning("wallet quality needs HELIUS_API_KEY; skipping")
        return
    async with db.pool().acquire() as con:
        wallets = [r["wallet"] for r in
                   await con.fetch("SELECT wallet FROM tracked_wallets")]
    if not wallets:
        return
    async with aiohttp.ClientSession() as sess:
        for w in wallets:
            try:
                m = await _metrics(sess, w)
                cls = classify(m["trades_per_day"], m["median_gap_min"],
                               m["sampled"])
                async with db.pool().acquire() as con:
                    if cls == BOT:
                        # mute: pin to the floor, but never below it
                        await con.execute(
                            "UPDATE tracked_wallets SET classification=$1, "
                            "trades_per_day=$2, median_gap_min=$3, "
                            "weight=LEAST(weight, 0.25), quality_checked_at=now() "
                            "WHERE wallet=$4",
                            cls, m["trades_per_day"], m["median_gap_min"], w)
                        log.info("MUTED bot wallet %s (%.0f trades/day, "
                                 "%.1fm median hold)", w[:6],
                                 m["trades_per_day"] or 0, m["median_gap_min"] or 0)
                    else:
                        await con.execute(
                            "UPDATE tracked_wallets SET classification=$1, "
                            "trades_per_day=$2, median_gap_min=$3, "
                            "quality_checked_at=now() WHERE wallet=$4",
                            cls, m["trades_per_day"], m["median_gap_min"], w)
                        log.info("wallet %s classified %s (%.1f trades/day, "
                                 "%.1fm hold)", w[:6], cls,
                                 m["trades_per_day"] or 0, m["median_gap_min"] or 0)
            except Exception as e:  # noqa: BLE001
                log.warning("quality check failed for %s: %s", w[:6], e)
            await asyncio.sleep(1.0)  # free-tier rps headroom


async def run() -> None:
    if not config.WALLET_QUALITY_ENABLED:
        log.info("wallet quality classifier disabled")
        return
    while True:
        try:
            await classify_all()
        except Exception as e:  # noqa: BLE001
            log.warning("wallet quality run error: %s", e)
        await asyncio.sleep(config.WALLET_QUALITY_INTERVAL_HOURS * 3600)
