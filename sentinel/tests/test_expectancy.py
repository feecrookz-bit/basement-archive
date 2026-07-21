from sentinel.modules import expectancy


def r(setup, val):
    return {"setup_type": setup, "r_result": val}


def test_cold_start_neutral(cfg):
    # fewer than min_trades -> neutral 1.0
    few = [r("ict", 2.0) for _ in range(3)]
    assert expectancy.from_results(few, cfg)["ict"] == 1.0


def test_winner_above_neutral(cfg):
    wins = [r("ict", 1.5) for _ in range(12)]
    m = expectancy.from_results(wins, cfg)["ict"]
    assert m > 1.0


def test_loser_below_neutral(cfg):
    losses = [r("range_play", -1.0) for _ in range(12)]
    m = expectancy.from_results(losses, cfg)["range_play"]
    assert m < 1.0


def test_clamp_bounds(cfg):
    lo, hi = cfg.get("conviction.expectancy.clamp")
    big_win = expectancy.from_results([r("ict", 50) for _ in range(12)], cfg)["ict"]
    big_loss = expectancy.from_results([r("ict", -50) for _ in range(12)], cfg)["ict"]
    assert big_win == hi and big_loss == lo


def test_window_limits_history(cfg):
    window = cfg.get("conviction.expectancy.window_trades")
    # old losses beyond the window are ignored; recent wins dominate
    old = [r("ict", -2.0) for _ in range(window)]
    recent = [r("ict", 2.0) for _ in range(window)]
    m = expectancy.from_results(old + recent, cfg)["ict"]
    assert m > 1.0


import pytest  # noqa: E402
from sentinel.ledger import MemoryLedger  # noqa: E402


@pytest.mark.asyncio
async def test_setup_expectancy_from_memory_ledger(cfg):
    L = MemoryLedger()
    # one closed winning ICT trade
    tid = await L.open_trade(1, "SOL/USDT", "ict", "backtest", None)
    await L.append_trade_event(tid, "OPENED", 1.0, 100, 0.1, 95, 0.0)
    await L.append_trade_event(tid, "CLOSED", -1.0, 110, 0.1, 95, 1.8)
    # below min_trades -> neutral regardless
    exp = await expectancy.setup_expectancy(L, cfg)
    assert exp.get("ict", 1.0) == 1.0
