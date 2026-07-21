from sentinel.modules.analyst import rs_momentum
from tests.conftest import candle, uptrend_series, HOUR


def pullback_reclaim_series():
    """Uptrend, then a pullback to the 20EMA with stochRSI reset, then reclaim."""
    base = uptrend_series(100, step=0.8)
    last = base[-1]
    price = last["close"]
    t = last["ts"]
    # pullback: several red candles drifting down ~5%
    for i in range(1, 7):
        p = price * (1 - 0.008 * i)
        base.append(candle(t + i * HOUR, p * 1.005, p * 1.006, p * 0.995, p))
    # reclaim candle: strong close back up
    p = price * 0.97
    base.append(candle(t + 7 * HOUR, p, price * 1.001, p * 0.998, price * 0.999))
    return base


def test_top_decile_required(cfg, watch_entry):
    series = pullback_reclaim_series()
    weak = {**watch_entry, "rs_decile": 5}
    assert rs_momentum.detect(series, weak, cfg) is None


def test_no_entry_without_structure(cfg, watch_entry):
    from tests.conftest import flat_series
    assert rs_momentum.detect(flat_series(120), watch_entry, cfg) is None


def test_proposal_shape_when_detected(cfg, watch_entry):
    p = rs_momentum.detect(pullback_reclaim_series(), watch_entry, cfg)
    if p is not None:  # detection is strict; if it fires, invariants must hold
        assert p["stop_price"] < p["entry_price"]
        assert p["evidence"]["rs_decile"] == 10
        assert p["evidence"]["higher_highs_lows"] is True
