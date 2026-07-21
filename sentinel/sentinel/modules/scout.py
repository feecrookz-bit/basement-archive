"""SCOUT — ranked watchlist of tradeable alts, refreshed every 15 min.

Universe filter (volume, spread) -> relative strength vs BTC over
4h/24h/72h (weighted, recent counts most) -> unlock blacklist -> derivative
flags (data only). Output is a snapshot; Analyst reads it, nothing here
places trades.
"""
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("scout")


def perf_pct(closes: list[float], hours: int) -> float | None:
    """% change over the last `hours` 1h-candles."""
    if len(closes) <= hours or not closes[-hours - 1]:
        return None
    return 100 * (closes[-1] - closes[-hours - 1]) / closes[-hours - 1]


def rs_score(alt_closes: list[float], btc_closes: list[float], cfg) -> float | None:
    windows = cfg.get("scout.relative_strength.windows_hours", [4, 24, 72])
    weights = cfg.get("scout.relative_strength.weights", [0.5, 0.3, 0.2])
    score, used = 0.0, 0.0
    for w, wt in zip(windows, weights):
        pa, pb = perf_pct(alt_closes, w), perf_pct(btc_closes, w)
        if pa is None or pb is None:
            continue
        score += wt * (pa - pb)
        used += wt
    return round(score / used, 3) if used else None


def higher_lows_vs_btc(alt_closes: list[float], btc_closes: list[float],
                       window: int = 72, buckets: int = 3) -> bool:
    """Ratio ALT/BTC making higher lows across `buckets` slices of the window."""
    n = min(len(alt_closes), len(btc_closes), window)
    if n < buckets * 4:
        return False
    ratio = [a / b for a, b in zip(alt_closes[-n:], btc_closes[-n:]) if b]
    size = len(ratio) // buckets
    lows = [min(ratio[i * size:(i + 1) * size]) for i in range(buckets)]
    return all(lows[i] < lows[i + 1] for i in range(len(lows) - 1))


def load_unlocks(cfg, now: datetime | None = None) -> set[str]:
    """Symbols blacklisted for longs: >X% supply unlock within the window."""
    path = Path(cfg.get("scout.unlocks.csv_path", "data/unlocks.csv"))
    if not path.exists():
        return set()
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(days=cfg.get("scout.unlocks.window_days", 7))
    min_pct = cfg.get("scout.unlocks.blacklist_supply_pct", 1.0)
    out = set()
    with path.open() as f:
        for row in csv.DictReader(r for r in f if not r.lstrip().startswith("#")):
            try:
                when = datetime.fromisoformat(row["unlock_at"].replace("Z", "+00:00"))
                pct = float(row["supply_pct"])
            except (KeyError, ValueError):
                continue
            if now <= when <= horizon and pct >= min_pct:
                out.add(row["symbol"].strip().upper())
    return out


async def build_watchlist(market, ledger, bus, cfg) -> dict:
    universe = await market.universe()
    exclude = set(cfg.get("scout.universe.exclude", []))
    min_vol = cfg.get("scout.universe.min_24h_volume_usd", 20_000_000)
    max_spread = cfg.get("scout.universe.max_spread_pct", 0.15)
    unlock_blacklist = load_unlocks(cfg, market.now())
    btc_closes = [c["close"] for c in await market.candles("BTC/USDT", "1h", 100)]

    entries = []
    for sym in universe:
        if sym in exclude or sym == "BTC/USDT":
            continue
        vol = await market.vol_24h_usd(sym)
        if not vol or vol < min_vol:
            continue
        spread = await market.spread_pct(sym)
        if spread is None or spread > max_spread:
            continue
        closes = [c["close"] for c in await market.candles(sym, "1h", 100)]
        score = rs_score(closes, btc_closes, cfg)
        if score is None:
            continue
        base = sym.split("/")[0]
        funding = await market.funding_pctile(sym)
        oi_chg = await market.oi_change_pct(sym)
        flags = {
            "unlock_blacklist": base in unlock_blacklist,
            "funding_extreme": funding is not None and funding >=
                cfg.get("scout.derivatives_overlay.funding_extreme_percentile", 95),
            "oi_loading": oi_chg is not None and oi_chg >=
                cfg.get("scout.derivatives_overlay.oi_spike_pct", 15),
        }
        hl = higher_lows_vs_btc(closes, btc_closes)
        if hl:
            score += cfg.get("scout.relative_strength.higher_lows_vs_btc_bonus", 0.15)
        entries.append({"pair": sym, "rs_score": round(score, 3),
                        "higher_lows_vs_btc": hl, "vol_24h_usd": vol,
                        "spread_pct": spread, "flags": flags})

    entries.sort(key=lambda e: e["rs_score"], reverse=True)
    top = entries[:cfg.get("scout.top_n", 15)]
    for rank, e in enumerate(top, 1):
        e["rank"] = rank
        n = len(entries)
        e["rs_decile"] = 10 - min(9, (rank - 1) * 10 // n) if n else None
    wl_id = await ledger.insert_watchlist(top, len(universe), cfg.version_id)
    snapshot = {"id": wl_id, "entries": top, "universe_size": len(universe)}
    await bus.publish("scout", "scout.watchlist", snapshot)
    log.info("watchlist: %d/%d pairs, top=%s", len(top), len(entries),
             top[0]["pair"] if top else None)
    return snapshot
