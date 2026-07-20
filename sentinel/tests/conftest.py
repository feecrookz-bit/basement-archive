"""Fixture candle builders: deterministic synthetic series shaped like the
market phenomena the modules must recognise."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel import config as config_mod  # noqa: E402

HOUR = 3_600_000
T0 = 1_700_000_000_000


def candle(ts, o, h, l, c, v=1000.0):
    return {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def flat_series(n, price=100.0, wobble=0.5, start=T0):
    """Gentle range around `price`."""
    out = []
    for i in range(n):
        d = wobble if i % 2 == 0 else -wobble
        out.append(candle(start + i * HOUR, price, price + abs(d) + 0.2,
                          price - abs(d) - 0.2, price + d))
    return out


def range_series(n=60, low=100.0, high=110.0, start=T0):
    """Respected horizontal range: alternating touches of both bands."""
    out = []
    for i in range(n):
        phase = i % 8
        if phase in (0, 1):        # tag the low
            out.append(candle(start + i * HOUR, low + 2, low + 3, low * 1.001, low + 1.5))
        elif phase in (4, 5):      # tag the high
            out.append(candle(start + i * HOUR, high - 2, high * 0.999, high - 3, high - 1.5))
        else:                      # middle
            mid = (low + high) / 2
            out.append(candle(start + i * HOUR, mid, mid + 1, mid - 1, mid))
    # leave price at the range low so the setup is actionable
    out[-1] = candle(start + (n - 1) * HOUR, low + 1, low + 1.5, low * 1.001, low + 0.4)
    return out


def uptrend_series(n=120, start_price=100.0, step=1.0, start=T0):
    """Rising zigzag: 7 candles up, 3 candles down per cycle — pullbacks show
    in highs AND lows, so pivot structure (higher highs/lows) actually forms."""
    out, price = [], start_price
    for i in range(n):
        prev = price
        price += step if (i % 10) < 7 else -0.7 * step
        o, c = prev, price
        out.append(candle(start + i * HOUR, o, max(o, c) + 0.3 * step,
                          min(o, c) - 0.3 * step, c))
    return out


def breakout_series(pre=80, resistance=110.0, post_break=6, start=T0,
                    retest=True, hold=True):
    """Range just below resistance, breakout candle on 3x volume, then an
    optional retest that optionally holds. The flat part trades close enough
    to the level that its capped highs define the resistance."""
    out = flat_series(pre, price=resistance - 1.5, wobble=1.5, start=start)
    for c in out:
        c["high"] = min(c["high"], resistance - 0.5)
    t = start + pre * HOUR
    # breakout candle: big volume close above resistance
    out.append(candle(t, 106, resistance * 1.03, 105.5, resistance * 1.025, v=3200.0))
    for i in range(1, post_break + 1):
        ts = t + i * HOUR
        if retest and i <= 2:  # pull back to the level
            out.append(candle(ts, resistance * 1.02, resistance * 1.02,
                              resistance * 1.002, resistance * 1.008))
        elif hold:
            out.append(candle(ts, resistance * 1.008, resistance * 1.015,
                              resistance * 1.001, resistance * 1.012))
        else:      # retest fails: close below level
            out.append(candle(ts, resistance * 1.005, resistance * 1.006,
                              resistance * 0.97, resistance * 0.98))
    return out


@pytest.fixture
def cfg(tmp_path):
    src = Path(__file__).resolve().parent.parent / "config.yaml"
    return config_mod.load(src)


@pytest.fixture
def watch_entry():
    return {"pair": "ALT/USDT", "rs_score": 2.0, "rank": 1, "rs_decile": 10,
            "higher_lows_vs_btc": False, "vol_24h_usd": 50_000_000,
            "spread_pct": 0.05,
            "flags": {"unlock_blacklist": False, "funding_extreme": False,
                      "oi_loading": False}}
