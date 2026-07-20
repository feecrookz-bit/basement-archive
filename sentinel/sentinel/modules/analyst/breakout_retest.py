"""Setup B — breakout-retest.

Break of multi-day resistance on >= 2x average volume, then a pullback that
retests the level within 24h and holds (1h close back above it). The entry
is the RETEST HOLD — never the breakout candle itself. That ban is a hard
invariant enforced here in code (and pinned by a dedicated test): if the
most recent candle IS the breakout candle, there is no proposal, full stop.
Invalidation: 1h close back below the level.
"""
RETEST_TOL_PCT = 1.0  # pullback low within this % of the level = a retest


def detect(candles: list[dict], watch_entry: dict, cfg) -> dict | None:
    lookback_days = int(cfg.get("analyst.setups.breakout_retest.resistance_lookback_days", 3))
    vol_mult = cfg.get("analyst.setups.breakout_retest.breakout_volume_mult", 2.0)
    retest_window = int(cfg.get("analyst.setups.breakout_retest.retest_window_hours", 24))
    lookback = lookback_days * 24
    if len(candles) <= lookback:
        return None

    # find the breakout candle: first close above the prior multi-day high,
    # searched over the recent retest window (only where full history exists)
    start = max(lookback, len(candles) - retest_window)
    for i in range(start, len(candles)):
        hist = candles[i - lookback:i]
        resistance = max(c["high"] for c in hist)
        c = candles[i]
        if c["close"] <= resistance:
            continue
        avg_vol = sum(x["volume"] for x in hist) / len(hist)
        if avg_vol <= 0 or c["volume"] < vol_mult * avg_vol:
            continue

        # ---- HARD INVARIANT: never buy the breakout candle itself ----
        if i == len(candles) - 1:
            return None

        # after the breakout: need a retest of the level and a hold
        post = candles[i + 1:]
        if len(post) > retest_window:
            return None  # too old, momentum spent
        touched = any(p["low"] <= resistance * (1 + RETEST_TOL_PCT / 100) for p in post)
        if not touched:
            return None
        last = post[-1]
        if last["close"] <= resistance:
            return None  # retest not held (or invalidated)
        entry = last["close"]
        stop = resistance * (1 - RETEST_TOL_PCT / 100)
        if entry <= stop:
            return None
        breakout_height = c["close"] - resistance
        target = entry + 2 * (entry - stop)  # measured 2R objective
        return {
            "entry_price": round(entry, 10),
            "stop_price": round(stop, 10),
            "targets": [{"price": round(target, 10), "r_multiple": 2.0}],
            "evidence": {
                "resistance": resistance,
                "breakout_ts": c["ts"], "breakout_close": c["close"],
                "breakout_volume": c["volume"], "avg_volume": round(avg_vol, 2),
                "volume_mult": round(c["volume"] / avg_vol, 2),
                "retest_low": min(p["low"] for p in post),
                "hours_since_breakout": len(post),
                "watchlist_entry": watch_entry,
            },
        }
    return None
