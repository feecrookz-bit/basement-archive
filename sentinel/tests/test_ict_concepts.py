from sentinel import indicators as ind
from sentinel.modules.ict import concepts as cx
from tests.conftest import candle, flat_series, uptrend_series


def test_pivot_points_returns_indices():
    highs, lows = ind.pivot_points(uptrend_series(60))
    assert highs and lows
    assert all(isinstance(i, int) and p > 0 for i, p in highs + lows)


def test_bullish_fvg_detected():
    cs = [candle(0, 100, 101, 99, 100.5),
          candle(1, 100.5, 104, 100.4, 103.8),   # displacement
          candle(2, 103.8, 105, 102.5, 104.5)]   # low 102.5 > high 101 = gap
    gaps = cx.fvgs(cs, atr_now=1.0, min_atr_frac=0.25)
    bulls = [g for g in gaps if g["side"] == "bull"]
    assert bulls and bulls[0]["low"] == 101 and bulls[0]["high"] == 102.5
    assert bulls[0]["filled"] is False


def test_fvg_fill_marks_filled():
    cs = [candle(0, 100, 101, 99, 100.5),
          candle(1, 100.5, 104, 100.4, 103.8),
          candle(2, 103.8, 105, 102.5, 104.5),
          candle(3, 104.5, 104.6, 100.5, 101.0)]  # trades through the gap
    bulls = [g for g in cx.fvgs(cs, 1.0) if g["side"] == "bull"]
    assert bulls[0]["filled"] is True


def test_no_fvg_on_overlapping_candles():
    assert [g for g in cx.fvgs(flat_series(30), 1.0) if g["side"] == "bull"] == []


def test_order_block_is_last_bearish_before_displacement():
    cs = [candle(0, 100, 100.5, 99.5, 100.2),
          candle(1, 100.2, 100.4, 99.2, 99.4),   # bearish -> the OB
          candle(2, 99.4, 103.5, 99.3, 103.4)]   # displacement (body 4.0 >= 1.5*ATR)
    obs = cx.order_blocks(cs, atr_now=1.0, atr_mult=1.5)
    assert obs and obs[0]["idx"] == 1
    assert obs[0]["low"] == 99.2 and obs[0]["high"] == 100.2


def test_sweep_requires_reclaim():
    level = 100.0
    swept = [candle(0, 100.5, 100.6, 99.2, 100.3)]     # wick below, close above
    broke = [candle(0, 100.5, 100.6, 99.2, 99.5)]      # closed below
    assert cx.sweep(swept, level) is not None
    assert cx.sweep(broke, level) is None


def test_sweep_invalidated_by_later_breakdown():
    level = 100.0
    cs = [candle(0, 100.5, 100.6, 99.2, 100.3),   # sweep...
          candle(1, 100.3, 100.4, 98.5, 99.0)]    # ...then breakdown
    assert cx.sweep(cs, level) is None


def test_equal_lows_cluster():
    lows = [(5, 100.0), (12, 100.05), (20, 104.0), (30, 100.1)]
    pools = cx.equal_lows(lows, tol_pct=0.15)
    assert len(pools) == 1 and pools[0]["count"] == 3
    assert pools[0]["level"] == 100.0


def test_ote_band_math():
    lo, hi = cx.ote_band(100.0, 110.0, 0.62, 0.79)
    assert abs(lo - (110 - 7.9)) < 1e-9   # 79% retrace
    assert abs(hi - (110 - 6.2)) < 1e-9   # 62% retrace
    assert lo < hi


def test_mss_confirms_after_sweep():
    cs = [candle(i, 100, 101 + (i == 3), 99, 100) for i in range(8)]
    # swing high 102 at idx 3 (strength 2); sweep at idx 5; close above at idx 7
    cs[7] = candle(7, 101, 103, 100.9, 102.5)
    highs, _ = __import__("sentinel.indicators", fromlist=["x"]).pivot_points(cs)
    got = cx.mss(cs, after_idx=5, pivot_highs=highs)
    assert got and got["idx"] == 7


def test_smt_divergence():
    alt = [candle(i, 100, 101, 100 - (3 if i >= 30 else 2), 100) for i in range(40)]
    ref = [candle(i, 100, 101, 100 - (1 if i >= 30 else 2), 100) for i in range(40)]
    assert cx.smt_divergence(alt, ref, window=10) is True
    assert cx.smt_divergence(ref, alt, window=10) is False
