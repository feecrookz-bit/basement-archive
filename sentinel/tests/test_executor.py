from sentinel.modules.executor import TradeState, paper_fill, step_trade
from tests.conftest import flat_series


def fresh_state():
    # entry 100, stop 95 -> 1R = 5
    return TradeState(trade_id="t1", pair="SOL/USDT", entry=100.0, stop=95.0,
                      qty=10.0, initial_qty=10.0)


def test_paper_fill_costs(cfg):
    f = paper_fill("buy", 100.0, 0.10, 1000.0, cfg)
    assert f["price"] > 100.0                       # buys fill worse
    assert abs(f["fees_quote"] - 1.0) < 1e-9        # 0.1% of 1000
    s = paper_fill("sell", 100.0, 0.10, 1000.0, cfg)
    assert s["price"] < 100.0                       # sells fill worse


def test_ladder_tp1_sells_half_and_moves_stop_to_breakeven(cfg):
    st = fresh_state()
    actions = step_trade(st, 107.5, flat_series(24), cfg)  # 1.5R
    types = [a["type"] for a in actions]
    assert "PARTIAL_EXIT_TP1" in types
    assert "STOP_TO_BREAKEVEN" in types
    tp1 = next(a for a in actions if a["type"] == "PARTIAL_EXIT_TP1")
    assert abs(tp1["sell_qty"] - 5.0) < 1e-9        # 50%
    assert st.stop == 100.0                          # breakeven
    assert abs(st.qty - 5.0) < 1e-9


def test_ladder_tp2_sells_quarter(cfg):
    st = fresh_state()
    step_trade(st, 107.5, flat_series(24), cfg)      # TP1
    actions = step_trade(st, 112.5, flat_series(24), cfg)  # 2.5R
    tp2 = next(a for a in actions if a["type"] == "PARTIAL_EXIT_TP2")
    assert abs(tp2["sell_qty"] - 2.5) < 1e-9        # 25% of initial
    assert abs(st.qty - 2.5) < 1e-9                 # trailing remainder


def test_stop_hit_closes_everything(cfg):
    st = fresh_state()
    actions = step_trade(st, 94.0, flat_series(24), cfg)
    assert actions[0]["type"] == "STOP_HIT"
    assert abs(actions[0]["sell_qty"] - 10.0) < 1e-9
    assert st.qty == 0


def test_breakeven_protects_after_tp1(cfg):
    st = fresh_state()
    step_trade(st, 107.5, flat_series(24), cfg)      # TP1 + BE
    actions = step_trade(st, 99.0, flat_series(24), cfg)  # falls back under entry
    assert actions[0]["type"] == "TRAIL_HIT"         # stop was at breakeven
    assert st.qty == 0


def test_trail_moves_up_with_swing_low(cfg):
    st = fresh_state()
    step_trade(st, 107.5, flat_series(24), cfg)      # TP1 done -> trailing active
    high_candles = flat_series(24, price=106.0, wobble=0.3)
    actions = step_trade(st, 108.0, high_candles, cfg)
    trail = [a for a in actions if a["type"] == "TRAIL_MOVED"]
    assert trail and trail[0]["stop"] > 100.0        # ratcheted above breakeven


def test_no_action_when_flat(cfg):
    st = fresh_state()
    st.qty = 0
    assert step_trade(st, 200.0, flat_series(24), cfg) == []
