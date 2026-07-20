"""Setup A — range play.

Pair has respected a horizontal range >= min_touches per side over
>= min_range_age_hours on 1h candles. Entry: limit at range low + buffer.
Invalidation: close below range low. Target: range high.
"""
TOUCH_TOL_PCT = 0.6  # a candle extreme within this % of the level counts as a touch


def detect(candles: list[dict], watch_entry: dict, cfg) -> dict | None:
    min_age = int(cfg.get("analyst.setups.range_play.min_range_age_hours", 48))
    min_touches = int(cfg.get("analyst.setups.range_play.min_touches_per_side", 3))
    buffer_pct = cfg.get("analyst.setups.range_play.entry_buffer_pct", 0.3)
    if len(candles) < min_age:
        return None
    window = candles[-min_age:]
    range_low = min(c["low"] for c in window)
    range_high = max(c["high"] for c in window)
    if range_low <= 0 or range_high <= range_low:
        return None
    height_pct = 100 * (range_high - range_low) / range_low
    if height_pct < 3:  # too tight to pay for fees/slippage
        return None

    low_touches = sum(1 for c in window
                      if abs(c["low"] - range_low) / range_low * 100 <= TOUCH_TOL_PCT)
    high_touches = sum(1 for c in window
                       if abs(c["high"] - range_high) / range_high * 100 <= TOUCH_TOL_PCT)
    if low_touches < min_touches or high_touches < min_touches:
        return None

    # respected range = no 1h close outside it
    if any(c["close"] < range_low or c["close"] > range_high for c in window):
        return None

    last = window[-1]
    entry = range_low * (1 + buffer_pct / 100)
    # actionable only when price is actually at the low of the range
    if last["close"] > entry * 1.01:
        return None
    stop = range_low * (1 - buffer_pct / 100)
    if entry <= stop:
        return None
    r1 = (range_high - entry) / (entry - stop)
    return {
        "entry_price": round(entry, 10),
        "stop_price": round(stop, 10),
        "targets": [{"price": round(range_high, 10), "r_multiple": round(r1, 2)}],
        "evidence": {
            "range_low": range_low, "range_high": range_high,
            "range_height_pct": round(height_pct, 2),
            "low_touches": low_touches, "high_touches": high_touches,
            "range_age_hours": min_age, "last_close": last["close"],
            "watchlist_entry": watch_entry,
        },
    }
