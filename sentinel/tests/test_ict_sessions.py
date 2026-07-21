from datetime import datetime, timezone

from sentinel.modules.ict import sessions as sx
from tests.conftest import candle

M15 = 900_000


def day_candles(day_start_ms, lows_by_hour=None, highs_by_hour=None, until_hour=24):
    """One UTC day of 15m candles at ~100, with optional extreme overrides."""
    out = []
    for q in range(until_hour * 4):
        ts = day_start_ms + q * M15
        hour = q // 4
        hi = (highs_by_hour or {}).get(hour, 100.5)
        lo = (lows_by_hour or {}).get(hour, 99.5)
        out.append(candle(ts, 100, hi, lo, 100.1))
    return out


DAY0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC exactly


def test_session_high_low_bucketing():
    cs = day_candles(DAY0, lows_by_hour={3: 98.0}, highs_by_hour={10: 103.0})
    now = datetime.fromtimestamp((DAY0 + 21 * 3_600_000) / 1000, tz=timezone.utc)
    st = sx.session_state(cs, now)
    assert st["asia"]["low"] == 98.0          # 03:00 low lands in asia (00-08)
    assert st["london"]["high"] == 103.0      # 10:00 high lands in london (07-12)
    assert st["asia"]["status"] == "closed"
    assert st["current"] is None              # 21:00 = all sessions closed


def test_session_swept_flags():
    # asia low 98 at 03:00; at 14:00 price wicks 97.5 -> asia L swept
    cs = day_candles(DAY0, lows_by_hour={3: 98.0, 14: 97.5})
    now = datetime.fromtimestamp((DAY0 + 15 * 3_600_000) / 1000, tz=timezone.utc)
    st = sx.session_state(cs, now)
    assert st["asia"]["low_swept"] is True
    assert st["asia"]["high_swept"] is False
    assert st["current"] == "newyork"


def test_waiting_session():
    cs = day_candles(DAY0, until_hour=6)
    now = datetime.fromtimestamp((DAY0 + 5 * 3_600_000) / 1000, tz=timezone.utc)
    st = sx.session_state(cs, now)
    assert st["newyork"]["status"] == "waiting"
    assert st["asia"]["status"] == "open"
    assert st["current"] == "asia"


def test_day_levels_pdh_pdl_and_hits():
    HOUR = 3_600_000
    cs = []
    # yesterday: high 105 low 95
    for h in range(24):
        cs.append(candle(DAY0 - 24 * HOUR + h * HOUR, 100,
                         105 if h == 12 else 101, 95 if h == 4 else 99, 100))
    # today so far: pokes above 105 at 02:00
    for h in range(5):
        cs.append(candle(DAY0 + h * HOUR, 100, 105.5 if h == 2 else 101, 99, 100))
    now = datetime.fromtimestamp((DAY0 + 5 * HOUR) / 1000, tz=timezone.utc)
    lv = sx.day_levels(cs, now)
    assert lv["pdh"] == 105 and lv["pdl"] == 95
    assert lv["pdh_hit"] is True
    assert lv["pdl_hit"] is False
