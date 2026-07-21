"""The ICT long setup — the full bullish sequence, or nothing.

Order of proof, every stage mandatory (config can only relax MSS):
  1. SWEEP    — a key sell-side level (session low, PDL, or an equal-lows
                pool) was wicked below and reclaimed within the lookback.
  2. DISPLACE — after the sweep, a displacement candle up left a bullish
                FVG (imbalance = intent).
  3. MSS      — a close above the nearest pre-sweep swing high
                (config `ict.require_mss`).
  4. ENTRY    — the CURRENT candle is retracing inside the FVG ∩ OTE band
                (or the displacement's order block). We buy the discount,
                never the displacement candle itself.
Stop below the sweep low; target = nearest resting buy-side liquidity
above (session high / PDH / PWH); reject if R:R < `ict.min_rr`.
"""
from ... import indicators as ind
from . import concepts as cx


def _key_lows(sess: dict, levels: dict, eq_lows: list[dict]) -> list[dict]:
    """Candidate sell-side levels, labeled."""
    out = []
    for name in ("asia", "london", "newyork"):
        s = sess.get(name) or {}
        if s.get("low") is not None and s.get("status") == "closed":
            out.append({"label": f"{name}_low", "level": s["low"]})
    if levels.get("pdl") is not None:
        out.append({"label": "PDL", "level": levels["pdl"]})
    for pool in eq_lows:
        out.append({"label": f"equal_lows_x{pool['count']}",
                    "level": pool["level"]})
    return out


def _buy_side_targets(sess: dict, levels: dict, above: float) -> list[dict]:
    out = []
    for name in ("asia", "london", "newyork"):
        s = sess.get(name) or {}
        if s.get("high") is not None and s["high"] > above:
            out.append({"label": f"{name}_high", "level": s["high"]})
    for key in ("pdh", "pwh"):
        if levels.get(key) is not None and levels[key] > above:
            out.append({"label": key.upper(), "level": levels[key]})
    out.sort(key=lambda t: t["level"])
    return out


def detect(candles_15m: list[dict], ref_15m: list[dict], sess: dict,
           levels: dict, watch_entry: dict, cfg) -> dict | None:
    lookback = int(cfg.get("ict.sweep_lookback_candles", 96))
    if len(candles_15m) < 40:
        return None
    atr_now = cx.atr(candles_15m)
    if not atr_now:
        return None

    pivot_highs, pivot_lows = ind.pivot_points(candles_15m)
    eq = cx.equal_lows(pivot_lows, cfg.get("ict.equal_lows_tol_pct", 0.15))

    # ---- 1. sweep of a key low ----
    since = max(0, len(candles_15m) - lookback)
    best = None
    for cand in _key_lows(sess, levels, eq):
        hit = cx.sweep(candles_15m, cand["level"], since_idx=since)
        if hit and (best is None or hit["idx"] > best["idx"]):
            best = {**hit, "label": cand["label"]}
    if best is None:
        return None
    sweep_idx, sweep_low = best["idx"], best["sweep_low"]

    # ---- 2. displacement up leaving a bullish FVG, after the sweep ----
    post = candles_15m[sweep_idx:]
    gaps = [g for g in cx.fvgs(post, atr_now,
                               cfg.get("ict.fvg_min_atr_frac", 0.25))
            if g["side"] == "bull" and not g["filled"]]
    if not gaps:
        return None
    gap = gaps[-1]
    gap_abs_idx = sweep_idx + gap["idx"]

    # ---- 3. MSS confirm ----
    struct = cx.mss(candles_15m, sweep_idx, pivot_highs)
    if cfg.get("ict.require_mss", True) and struct is None:
        return None

    # ---- 4. entry: current candle retracing into FVG ∩ OTE (or the OB) ----
    leg_high = max(c["high"] for c in candles_15m[sweep_idx:])
    ote_lo, ote_hi = cx.ote_band(sweep_low, leg_high, *cfg.get("ict.ote", [0.62, 0.79]))
    last = candles_15m[-1]
    if len(candles_15m) - 1 <= gap_abs_idx:
        return None  # never buy the displacement candle itself
    in_fvg = gap["low"] <= last["close"] <= gap["high"]
    in_ote = ote_lo <= last["close"] <= ote_hi
    obs = [o for o in cx.order_blocks(post, atr_now,
                                      cfg.get("ict.displacement_atr_mult", 1.5))]
    in_ob = any(o["low"] <= last["close"] <= o["high"] for o in obs)
    if not ((in_fvg and in_ote) or in_ob):
        return None

    entry = last["close"]
    stop = sweep_low * (1 - 0.001)
    if entry <= stop:
        return None
    targets = _buy_side_targets(sess, levels, entry)
    if not targets:
        return None
    tgt = targets[0]
    rr = (tgt["level"] - entry) / (entry - stop)
    if rr < cfg.get("ict.min_rr", 2.0):
        return None

    smt = cx.smt_divergence(candles_15m, ref_15m)
    return {
        "entry_price": round(entry, 10),
        "stop_price": round(stop, 10),
        "targets": [{"price": round(t["level"], 10), "label": t["label"],
                     "r_multiple": round((t["level"] - entry) / (entry - stop), 2)}
                    for t in targets[:2]],
        "evidence": {
            "sweep": {"label": best["label"], "level": best["level"],
                      "sweep_low": sweep_low, "idx": sweep_idx},
            "fvg": {"low": gap["low"], "high": gap["high"]},
            "mss": struct,
            "ote_band": [round(ote_lo, 10), round(ote_hi, 10)],
            "entered_via": "fvg_ote" if (in_fvg and in_ote) else "order_block",
            "rr_first_target": round(rr, 2),
            "smt_divergence": smt,
            "session_state": sess,
            "day_levels": levels,
            "watchlist_entry": watch_entry,
        },
    }
