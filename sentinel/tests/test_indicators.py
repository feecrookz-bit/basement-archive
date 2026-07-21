from sentinel import indicators as ind
from tests.conftest import candle, flat_series, uptrend_series


def test_ema_converges_to_constant():
    series = ind.ema([100.0] * 50, 20)
    assert abs(series[-1] - 100.0) < 1e-9


def test_ema_alignment_length():
    vals = [float(i) for i in range(60)]
    assert len(ind.ema(vals, 20)) == 60


def test_atr_positive_and_scales():
    calm = flat_series(40, wobble=0.2)
    wild = flat_series(40, wobble=3.0)
    assert ind.atr(wild) > ind.atr(calm) > 0


def test_percentile_rank():
    assert ind.percentile_rank([1, 2, 3, 4, 5], 5) == 100.0
    assert ind.percentile_rank([1, 2, 3, 4], 1) == 25.0
    assert ind.percentile_rank([], 1) is None


def test_stoch_rsi_extremes():
    up = [100 + i * 0.5 for i in range(80)]
    assert ind.stoch_rsi(up) is not None
    down = [100 - i * 0.5 for i in range(80)]
    sr_down = ind.stoch_rsi(down)
    assert sr_down is not None and sr_down <= 50


def test_swing_low():
    cs = [candle(i, 10, 11, 10 - (i == 5), 10.5) for i in range(12)]
    assert ind.swing_low(cs, 12) == 9.0


def test_higher_highs_lows_on_uptrend():
    assert ind.higher_highs_lows(uptrend_series(80)) is True
    assert ind.higher_highs_lows(flat_series(80, wobble=0.5)) is False
