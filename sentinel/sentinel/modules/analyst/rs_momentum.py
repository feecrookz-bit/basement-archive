"""Setup C — RS momentum continuation.

Top-decile RS pair in an uptrend structure (higher highs/lows), pulled back
to the 20 EMA on 1h with a stochRSI reset, entering on the EMA reclaim.
Invalidation: structure low break.
"""
from ... import indicators as ind

EMA_TOUCH_TOL_PCT = 1.0
RESET_LOOKBACK = 12  # stochRSI must have reset within the last N candles


def detect(candles: list[dict], watch_entry: dict, cfg) -> dict | None:
    decile_min = int(cfg.get("analyst.setups.rs_momentum.rs_decile_min", 10))
    ema_period = int(cfg.get("analyst.setups.rs_momentum.pullback_ema", 20))
    reset_below = cfg.get("analyst.setups.rs_momentum.stochrsi_reset_below", 20)

    if (watch_entry.get("rs_decile") or 0) < decile_min:
        return None
    if len(candles) < 80:
        return None
    if not ind.higher_highs_lows(candles):
        return None

    closes = [c["close"] for c in candles]
    ema_series = ind.ema(closes, ema_period)
    if not ema_series:
        return None
    ema_now = ema_series[-1]

    # pullback: some recent candle tagged the EMA
    recent = candles[-RESET_LOOKBACK:]
    recent_emas = ema_series[-RESET_LOOKBACK:]
    touched = any(c["low"] <= e * (1 + EMA_TOUCH_TOL_PCT / 100)
                  for c, e in zip(recent, recent_emas))
    if not touched:
        return None

    # stochRSI reset during the pullback
    sr_series = ind.stoch_rsi_series(closes)
    if not sr_series or min(sr_series[-RESET_LOOKBACK:]) > reset_below:
        return None

    # entry on reclaim: last candle closes back above the EMA
    last = candles[-1]
    if last["close"] <= ema_now:
        return None

    _, lows = ind.pivots(candles)
    if not lows:
        return None
    structure_low = lows[-1]
    entry = last["close"]
    if entry <= structure_low:
        return None
    target = entry + 2 * (entry - structure_low)
    return {
        "entry_price": round(entry, 10),
        "stop_price": round(structure_low, 10),
        "targets": [{"price": round(target, 10), "r_multiple": 2.0}],
        "evidence": {
            "rs_decile": watch_entry.get("rs_decile"),
            "rs_score": watch_entry.get("rs_score"),
            "ema_period": ema_period, "ema_value": round(ema_now, 10),
            "stochrsi_min_recent": min(sr_series[-RESET_LOOKBACK:]),
            "structure_low": structure_low,
            "higher_highs_lows": True,
            "watchlist_entry": watch_entry,
        },
    }
