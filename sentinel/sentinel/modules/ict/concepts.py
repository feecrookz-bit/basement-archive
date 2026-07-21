"""ICT primitives — pure functions over candle lists, no I/O.

Definitions used (long-side only, this engine is spot):
  - FVG (fair value gap): 3-candle imbalance. Bullish when candle[i-2].high
    < candle[i].low — the middle candle displaced without overlap.
  - Order block: the last bearish candle before a bullish displacement leg;
    its (low, open) is the zone institutions defended.
  - Liquidity sweep: price wicks BELOW a key low but the candle closes back
    above it — stops harvested, level held. A close below is a breakdown,
    not a sweep.
  - MSS (market structure shift): after a sweep, a close above the nearest
    prior swing high confirms the reversal.
  - OTE (optimal trade entry): the 62–79% retracement of the displacement
    leg.
  - SMT divergence: the alt makes a lower low while the reference (BTC)
    makes a higher low over the same window — relative strength at the
    sweep.
"""
from ... import indicators as ind


def body(c: dict) -> float:
    return abs(c["close"] - c["open"])


def is_bull(c: dict) -> bool:
    return c["close"] >= c["open"]


def fvgs(candles: list[dict], atr_now: float | None,
         min_atr_frac: float = 0.25) -> list[dict]:
    """Bullish + bearish fair value gaps, newest last.
    Each: {side, low, high, idx, filled} — bounds are the gap itself."""
    out: list[dict] = []
    min_gap = (atr_now or 0) * min_atr_frac
    for i in range(2, len(candles)):
        a, c = candles[i - 2], candles[i]
        # bullish gap
        if c["low"] > a["high"] and (c["low"] - a["high"]) >= min_gap:
            out.append({"side": "bull", "low": a["high"], "high": c["low"],
                        "idx": i, "filled": False})
        # bearish gap
        if c["high"] < a["low"] and (a["low"] - c["high"]) >= min_gap:
            out.append({"side": "bear", "low": c["high"], "high": a["low"],
                        "idx": i, "filled": False})
    # fill check: any later candle trading fully through the gap
    for g in out:
        for c in candles[g["idx"] + 1:]:
            if g["side"] == "bull" and c["low"] <= g["low"]:
                g["filled"] = True
                break
            if g["side"] == "bear" and c["high"] >= g["high"]:
                g["filled"] = True
                break
    return out


def displacement_legs(candles: list[dict], atr_now: float | None,
                      atr_mult: float = 1.5) -> list[int]:
    """Indices of bullish displacement candles (body >= mult * ATR)."""
    if not atr_now:
        return []
    return [i for i, c in enumerate(candles)
            if is_bull(c) and body(c) >= atr_mult * atr_now]


def order_blocks(candles: list[dict], atr_now: float | None,
                 atr_mult: float = 1.5) -> list[dict]:
    """Bullish order blocks: last bearish candle before a displacement-up
    candle. Zone = (low, open) of that bearish candle."""
    out = []
    for i in displacement_legs(candles, atr_now, atr_mult):
        j = i - 1
        while j >= 0 and is_bull(candles[j]):
            j -= 1
        if j >= 0:
            ob = candles[j]
            out.append({"side": "bull", "low": ob["low"], "high": ob["open"],
                        "idx": j, "displacement_idx": i})
    return out


def equal_lows(pivot_lows: list[tuple[int, float]],
               tol_pct: float = 0.15) -> list[dict]:
    """Clusters of >=2 pivot lows within tol — resting sell-side liquidity.
    Returns [{level, count, last_idx}] (level = min of cluster)."""
    out: list[dict] = []
    used: set[int] = set()
    for i, (idx_a, a) in enumerate(pivot_lows):
        if i in used:
            continue
        cluster = [(idx_a, a)]
        for j in range(i + 1, len(pivot_lows)):
            idx_b, b = pivot_lows[j]
            if a and abs(b - a) / a * 100 <= tol_pct:
                cluster.append((idx_b, b))
                used.add(j)
        if len(cluster) >= 2:
            out.append({"level": min(v for _, v in cluster),
                        "count": len(cluster),
                        "last_idx": max(ix for ix, _ in cluster)})
    return out


def sweep(candles: list[dict], level: float, since_idx: int = 0) -> dict | None:
    """Most recent sell-side sweep of `level` at/after since_idx:
    wick below, close back above. Close below = breakdown, not a sweep."""
    hit = None
    for i in range(max(since_idx, 0), len(candles)):
        c = candles[i]
        if c["low"] < level and c["close"] > level:
            hit = {"idx": i, "sweep_low": c["low"], "level": level}
        elif c["close"] < level:
            hit = None  # broke down after; any earlier sweep is invalidated
    return hit


def mss(candles: list[dict], after_idx: int,
        pivot_highs: list[tuple[int, float]]) -> dict | None:
    """First close above the nearest swing high formed before the sweep."""
    prior = [ph for ph in pivot_highs if ph[0] < after_idx]
    if not prior:
        return None
    _, level = prior[-1]
    for i in range(after_idx + 1, len(candles)):
        if candles[i]["close"] > level:
            return {"idx": i, "broken_high": level}
    return None


def ote_band(leg_low: float, leg_high: float,
             lo: float = 0.62, hi: float = 0.79) -> tuple[float, float]:
    """Price band of the 62–79% retracement of an up-leg (low..high).
    Returned as (band_low, band_high) in price terms."""
    span = leg_high - leg_low
    return (leg_high - hi * span, leg_high - lo * span)


def smt_divergence(alt: list[dict], ref: list[dict], window: int = 20) -> bool:
    """Alt lower-low while reference higher-low over the last `window`
    candles vs the prior `window` — relative strength divergence."""
    if len(alt) < 2 * window or len(ref) < 2 * window:
        return False
    alt_prev = min(c["low"] for c in alt[-2 * window:-window])
    alt_now = min(c["low"] for c in alt[-window:])
    ref_prev = min(c["low"] for c in ref[-2 * window:-window])
    ref_now = min(c["low"] for c in ref[-window:])
    return alt_now < alt_prev and ref_now > ref_prev


def atr(candles: list[dict], period: int = 14) -> float | None:
    return ind.atr(candles, period)
