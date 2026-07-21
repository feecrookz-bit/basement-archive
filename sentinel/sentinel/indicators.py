"""Pure indicator functions over candle lists.

A candle is a dict: {"ts": int_ms, "open": f, "high": f, "low": f,
"close": f, "volume": f}. Pure python, no numpy — deterministic and
trivially unit-testable; series lengths here are small (hundreds).
"""
import math


def ema(values: list[float], period: int) -> list[float]:
    """Full EMA series (same length as input; seeds with SMA of first period)."""
    if not values or len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    # left-pad so indexes align with input
    return [out[0]] * (period - 1) + out


def true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(candles: list[dict], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    trs = [true_range(candles[i - 1]["close"], c["high"], c["low"])
           for i, c in enumerate(candles) if i > 0]
    window = trs[-period:]
    return sum(window) / len(window)


def atr_series(candles: list[dict], period: int = 14) -> list[float]:
    out = []
    for i in range(period + 1, len(candles) + 1):
        a = atr(candles[:i], period)
        if a is not None:
            out.append(a)
    return out


def percentile_rank(series: list[float], value: float,
                    strict: bool = False) -> float | None:
    """0-100: fraction of series <= value (or < value when strict — use
    strict for 'is this actually elevated' questions; a constant series
    ranks itself at 100 otherwise)."""
    if not series:
        return None
    hits = sum(1 for s in series if (s < value if strict else s <= value))
    return round(100 * hits / len(series), 1)


def realized_vol(closes: list[float], window: int = 24) -> float | None:
    """Stdev of log returns over the window, annualized-ish per sqrt(window)."""
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var) * math.sqrt(window)


def rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 1:
        return []
    gains, losses, out = [], [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        out.append(100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l))
    return out


def stoch_rsi(closes: list[float], period: int = 14) -> float | None:
    """Last stochRSI value 0-100."""
    r = rsi(closes, period)
    if len(r) < period:
        return None
    window = r[-period:]
    lo, hi = min(window), max(window)
    if hi == lo:
        return 50.0
    return round(100 * (r[-1] - lo) / (hi - lo), 1)


def stoch_rsi_series(closes: list[float], period: int = 14) -> list[float]:
    out = []
    for i in range(2 * period + 1, len(closes) + 1):
        v = stoch_rsi(closes[:i], period)
        if v is not None:
            out.append(v)
    return out


def swing_low(candles: list[dict], lookback: int = 10) -> float | None:
    if not candles:
        return None
    return min(c["low"] for c in candles[-lookback:])


def pivots(candles: list[dict], strength: int = 2) -> tuple[list[float], list[float]]:
    """(pivot_highs, pivot_lows): local extremes with `strength` candles each side."""
    highs, lows = [], []
    for i in range(strength, len(candles) - strength):
        window = candles[i - strength: i + strength + 1]
        h, l = candles[i]["high"], candles[i]["low"]
        # skip consecutive duplicates: a flat top shared by adjacent candles
        # is one pivot, not two
        if h == max(c["high"] for c in window) and (not highs or highs[-1] != h):
            highs.append(h)
        if l == min(c["low"] for c in window) and (not lows or lows[-1] != l):
            lows.append(l)
    return highs, lows


def higher_highs_lows(candles: list[dict], strength: int = 2) -> bool:
    """Uptrend structure: last two pivot highs AND last two pivot lows ascending."""
    highs, lows = pivots(candles, strength)
    if len(highs) < 2 or len(lows) < 2:
        return False
    return highs[-1] > highs[-2] and lows[-1] > lows[-2]
