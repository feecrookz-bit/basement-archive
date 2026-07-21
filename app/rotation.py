"""
Rotation overlay — Method 6, the macro game. Data only, never a trade.

Tracks BTC dominance (share of total crypto market cap) via CoinGecko's
free global endpoint. The classic waterfall: BTC.D rising = money hiding
up the quality curve (risk-off for the long tail this system trades);
BTC.D rolling over while the market holds = the historical alt-season
signal; the long tail going vertical is itself the cycle-top tell.

This worker snapshots dominance hourly, classifies the regime from the
24h/7d deltas, and alerts only on regime *changes*. The dashboard shows
the current read. It cannot and does not predict — it labels the tide.
"""
import asyncio
import logging
from datetime import timedelta

import aiohttp

from . import config, db, notify

log = logging.getLogger("rotation")

RISK_OFF = "RISK_OFF"          # BTC.D rising: stay up the quality curve
ALT_ROTATION = "ALT_ROTATION"  # BTC.D falling: money moving down the curve
NEUTRAL = "NEUTRAL"


def classify(delta_24h_pp: float | None, shift_pp: float) -> str:
    """Regime from the 24h dominance delta in percentage points."""
    if delta_24h_pp is None:
        return NEUTRAL
    if delta_24h_pp >= shift_pp:
        return RISK_OFF
    if delta_24h_pp <= -shift_pp:
        return ALT_ROTATION
    return NEUTRAL


async def fetch_global(sess: aiohttp.ClientSession) -> dict | None:
    try:
        async with sess.get(config.COINGECKO_GLOBAL_URL, timeout=20) as r:
            if r.status != 200:
                log.warning("coingecko global -> HTTP %s", r.status)
                return None
            body = await r.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.warning("coingecko fetch failed: %s", e)
        return None
    data = (body or {}).get("data") or {}
    pct = data.get("market_cap_percentage") or {}
    caps = data.get("total_market_cap") or {}
    if pct.get("btc") is None:
        return None
    return {"btc_dominance": round(float(pct["btc"]), 3),
            "eth_dominance": round(float(pct.get("eth") or 0), 3),
            "total_mcap_usd": float(caps.get("usd") or 0)}


async def _delta(con, now_dom: float, hours: int) -> float | None:
    row = await con.fetchrow(
        f"""
        SELECT btc_dominance FROM market_rotation
        WHERE ts <= now() - interval '{hours} hours'
        ORDER BY ts DESC LIMIT 1
        """)
    if not row:
        return None
    return round(now_dom - row["btc_dominance"], 3)


async def snapshot() -> dict | None:
    """One poll: fetch, persist, compute deltas + state. Returns the reading."""
    async with aiohttp.ClientSession() as sess:
        g = await fetch_global(sess)
    if not g:
        return None
    async with db.pool().acquire() as con:
        d24 = await _delta(con, g["btc_dominance"], 24)
        d7d = await _delta(con, g["btc_dominance"], 24 * 7)
        await con.execute(
            "INSERT INTO market_rotation (btc_dominance, eth_dominance, total_mcap_usd) "
            "VALUES ($1,$2,$3)",
            g["btc_dominance"], g["eth_dominance"], g["total_mcap_usd"])
    state = classify(d24, config.ROTATION_SHIFT_PP)
    return {**g, "delta_24h_pp": d24, "delta_7d_pp": d7d, "state": state}


async def latest() -> dict | None:
    """Read model for /api/rotation — newest snapshot + deltas + state."""
    async with db.pool().acquire() as con:
        row = await con.fetchrow(
            "SELECT * FROM market_rotation ORDER BY ts DESC LIMIT 1")
        if not row:
            return None
        d24 = await _delta(con, row["btc_dominance"], 24)
        d7d = await _delta(con, row["btc_dominance"], 24 * 7)
    return {"ts": row["ts"], "btc_dominance": row["btc_dominance"],
            "eth_dominance": row["eth_dominance"],
            "total_mcap_usd": row["total_mcap_usd"],
            "delta_24h_pp": d24, "delta_7d_pp": d7d,
            "state": classify(d24, config.ROTATION_SHIFT_PP)}


async def run() -> None:
    if not config.ROTATION_ENABLED:
        log.info("rotation overlay disabled")
        return
    last_state: str | None = None
    while True:
        try:
            reading = await snapshot()
            if reading:
                log.info("BTC.D %.2f%% (24h %+0.2fpp) -> %s",
                         reading["btc_dominance"],
                         reading["delta_24h_pp"] or 0, reading["state"])
                if last_state is not None and reading["state"] != last_state \
                        and reading["state"] != NEUTRAL:
                    msg = ("BTC dominance rolling over — the historical "
                           "alt-season tell. Long-tail signals get tailwind; "
                           "remember the long tail going vertical is the "
                           "cycle-top signal itself."
                           if reading["state"] == ALT_ROTATION else
                           "BTC dominance rising — money is hiding up the "
                           "quality curve. Expect the long tail to bleed; "
                           "tighten expectations on open paper positions.")
                    await notify.send(
                        title=f"🔄 Rotation shift — {reading['state']}",
                        body=(f"BTC.D {reading['btc_dominance']}% "
                              f"({reading['delta_24h_pp']:+.2f}pp/24h, "
                              f"{(reading['delta_7d_pp'] or 0):+.2f}pp/7d)\n{msg}"),
                    )
                last_state = reading["state"]
        except Exception as e:  # noqa: BLE001
            log.warning("rotation worker error: %s", e)
        await asyncio.sleep(config.ROTATION_POLL_SECONDS)
