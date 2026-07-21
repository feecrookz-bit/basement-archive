from sentinel.modules import regime
from tests.conftest import candle, flat_series, uptrend_series, HOUR, T0


def downtrend_series(n=250, start_price=300.0, step=0.6):
    out, price = [], start_price
    for i in range(n):
        price -= step
        out.append(candle(T0 + i * HOUR, price + step, price + 0.4,
                          price - 0.4, price))
    return out


def test_uptrend_classifies_up(cfg):
    c1h = uptrend_series(250)
    c4h = uptrend_series(250)
    snap = regime.classify(c1h, c4h, cfg)
    assert snap["btc_state"] in (regime.TRENDING_UP, regime.TRENDING_UP_EARLY)


def test_downtrend_blocks_trading(cfg):
    snap = regime.classify(downtrend_series(), downtrend_series(), cfg)
    assert snap["btc_state"] == regime.TRENDING_DOWN
    assert snap["trading_allowed"] is False


def test_ranging_allows_trading(cfg):
    snap = regime.classify(flat_series(250, wobble=0.4),
                           flat_series(250, wobble=0.4), cfg)
    assert snap["btc_state"] == regime.RANGING
    assert snap["trading_allowed"] is True


def test_btc_kill_move_halts(cfg):
    c1h = flat_series(250, wobble=0.4)
    # last candle: +5% spike (> 3% kill threshold)
    prev_close = c1h[-2]["close"]
    spike = prev_close * 1.05
    c1h[-1] = candle(c1h[-1]["ts"], prev_close, spike + 1, prev_close - 1, spike)
    snap = regime.classify(c1h, flat_series(250, wobble=0.4), cfg)
    assert "btc_1h_move" in snap["kill_flags"]
    assert snap["trading_allowed"] is False


def test_short_history_defaults_ranging_not_crash(cfg):
    snap = regime.classify(flat_series(10), flat_series(10), cfg)
    assert snap["btc_state"] == regime.RANGING
