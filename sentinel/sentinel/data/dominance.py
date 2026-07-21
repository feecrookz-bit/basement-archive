"""BTC dominance reader for the regime rotation gate (keyless CoinGecko).

Method-6 macro tide: when BTC dominance is rising hard, capital is fleeing the
long tail — a bad time to open alt longs. This mirrors the tracker's proven
app/rotation.py logic, trimmed to the single question the regime gate asks:
how much has BTC.D risen over the last 24h? Best-effort and fail-open (returns
None on any error) so a data hiccup never wedges the engine.
"""
import logging

import aiohttp

log = logging.getLogger("dominance")

_prev: dict[str, float] = {"btc_d": None}  # simple in-process 24h-ago-ish baseline


async def btc_dominance(cfg) -> float | None:
    url = cfg.get("regime.rotation.coingecko_url",
                  "https://api.coingecko.com/api/v3/global")
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=20) as r:
                if r.status != 200:
                    return None
                body = await r.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.debug("dominance fetch failed: %s", e)
        return None
    pct = ((body or {}).get("data") or {}).get("market_cap_percentage") or {}
    d = pct.get("btc")
    return round(float(d), 3) if d is not None else None


async def rise_pp_24h(cfg) -> float | None:
    """Change in BTC.D vs the last observation (a coarse 24h proxy across the
    regime tick cadence). None until a baseline exists."""
    d = await btc_dominance(cfg)
    if d is None:
        return None
    prev = _prev["btc_d"]
    _prev["btc_d"] = d
    return None if prev is None else round(d - prev, 3)
