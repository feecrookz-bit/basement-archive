"""The never-buy-the-breakout-candle ban is a stated hard invariant of the
system — pinned here explicitly."""
from sentinel.modules.analyst import breakout_retest
from tests.conftest import breakout_series


def test_NEVER_buys_the_breakout_candle_itself(cfg, watch_entry):
    """Series ends ON the breakout candle -> absolutely no proposal."""
    series = breakout_series(post_break=0)
    assert series[-1]["volume"] > 3000  # it IS the breakout candle
    assert breakout_retest.detect(series, watch_entry, cfg) is None


def test_retest_hold_emits_entry(cfg, watch_entry):
    p = breakout_retest.detect(breakout_series(post_break=5), watch_entry, cfg)
    assert p is not None
    assert p["evidence"]["volume_mult"] >= 2.0
    assert p["entry_price"] > p["evidence"]["resistance"]
    assert p["stop_price"] < p["evidence"]["resistance"]


def test_failed_retest_no_entry(cfg, watch_entry):
    p = breakout_retest.detect(
        breakout_series(post_break=5, hold=False), watch_entry, cfg)
    assert p is None


def test_low_volume_breakout_ignored(cfg, watch_entry):
    series = breakout_series(post_break=5)
    for c in series:
        c["volume"] = 1000.0  # flatten volume: breakout candle no longer 2x
    assert breakout_retest.detect(series, watch_entry, cfg) is None
