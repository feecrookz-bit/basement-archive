"""Risk veto tests — the circuit breakers are tested explicitly, as the
build prompt demands."""
from sentinel.modules import risk


def proposal(pair="SOL/USDT", entry=100.0, stop=95.0):
    return {"id": 1, "pair": pair, "entry_price": entry, "stop_price": stop}


def state(**kw):
    defaults = dict(equity=10_000.0, open_positions=[], entries_last_24h=0,
                    daily_pnl_pct=0.0, weekly_pnl_pct=0.0, halted=False)
    defaults.update(kw)
    return risk.AccountState(**defaults)


# ---- sizing: the stop distance determines size, never the reverse ----
def test_sizing_formula():
    s = risk.size_position(10_000, 0.75, 100.0, 95.0)
    assert s["risk_quote"] == 75.0            # 0.75% of 10k
    assert abs(s["qty"] - 15.0) < 1e-9        # 75 / (100-95)
    assert s["notional"] == 1500.0


def test_sizing_wider_stop_means_smaller_position():
    tight = risk.size_position(10_000, 0.75, 100.0, 98.0)
    wide = risk.size_position(10_000, 0.75, 100.0, 90.0)
    assert wide["qty"] < tight["qty"]
    assert abs(wide["risk_quote"] - tight["risk_quote"]) < 1e-9  # same risk


def test_sizing_rejects_stop_above_entry():
    assert risk.size_position(10_000, 0.75, 95.0, 100.0) is None


def test_accepts_clean_proposal(cfg):
    v = risk.evaluate(proposal(), state(), cfg)
    assert v["decision"] == "accepted"
    assert v["sizing"]["risk_pct"] == 0.75


# ---- circuit breakers (explicit) ----
def test_daily_breaker_rejects(cfg):
    v = risk.evaluate(proposal(), state(daily_pnl_pct=-2.0), cfg)
    assert v["decision"] == "rejected"
    assert any(r.startswith("daily_breaker") for r in v["reject_reasons"])


def test_weekly_breaker_rejects(cfg):
    v = risk.evaluate(proposal(), state(weekly_pnl_pct=-5.1), cfg)
    assert v["decision"] == "rejected"
    assert any(r.startswith("weekly_breaker") for r in v["reject_reasons"])


def test_breaker_check_daily_triggers_flatten(cfg):
    halt = risk.breaker_check(state(daily_pnl_pct=-2.5), cfg)
    assert halt and halt["scope"] == "daily" and halt["flatten"]


def test_breaker_check_weekly_beats_daily(cfg):
    halt = risk.breaker_check(state(daily_pnl_pct=-3.0, weekly_pnl_pct=-6.0), cfg)
    assert halt["scope"] == "weekly"
    assert "manual restart" in halt["reason"]


def test_no_breaker_when_healthy(cfg):
    assert risk.breaker_check(state(daily_pnl_pct=-1.9, weekly_pnl_pct=-4.9), cfg) is None


# ---- caps and governor ----
def test_max_concurrent(cfg):
    positions = [{"pair": f"X{i}/USDT", "sector": None, "risk_quote": 10}
                 for i in range(3)]
    v = risk.evaluate(proposal(), state(open_positions=positions), cfg)
    assert any(r.startswith("max_concurrent") for r in v["reject_reasons"])


def test_total_open_risk_cap(cfg):
    positions = [{"pair": "X/USDT", "sector": None, "risk_quote": 150.0}]
    # existing 150 + new 75 = 225 > 2% of 10k (200)
    v = risk.evaluate(proposal(), state(open_positions=positions), cfg)
    assert any(r.startswith("max_open_risk") for r in v["reject_reasons"])


def test_sector_cap(cfg):
    positions = [{"pair": "AVAX/USDT", "sector": "L1", "risk_quote": 10}]
    v = risk.evaluate(proposal("SOL/USDT"), state(open_positions=positions), cfg)
    assert any(r.startswith("sector_cap") for r in v["reject_reasons"])


def test_overtrading_governor(cfg):
    v = risk.evaluate(proposal(), state(entries_last_24h=4), cfg)
    assert any(r.startswith("overtrading_governor") for r in v["reject_reasons"])


def test_no_averaging_down_same_pair(cfg):
    positions = [{"pair": "SOL/USDT", "sector": "L1", "risk_quote": 10}]
    v = risk.evaluate(proposal("SOL/USDT"), state(open_positions=positions), cfg)
    assert "already_in_pair" in v["reject_reasons"]


def test_halt_blocks_everything(cfg):
    v = risk.evaluate(proposal(), state(halted=True), cfg)
    assert "halt_active" in v["reject_reasons"]


# ---- conviction sizing: scales within bounds, hard caps STILL veto ----
def test_conviction_sizing_bounded(cfg):
    base = cfg.get("risk.risk_per_trade_pct")
    lo = cfg.get("conviction.sizing.min_mult")
    hi = cfg.get("conviction.sizing.max_mult")
    assert risk.conviction_risk_pct(None, cfg) == base          # no conviction -> base
    assert risk.conviction_risk_pct(0.01, cfg) == round(base * lo, 4)  # floor
    assert risk.conviction_risk_pct(999, cfg) == round(base * hi, 4)   # ceiling


def test_high_conviction_sizes_up_but_caps_hold(cfg):
    # a max-conviction proposal risks more per trade...
    hi_conv = {**proposal(), "conviction": 99}
    v = risk.evaluate(hi_conv, state(), cfg)
    assert v["decision"] == "accepted"
    assert v["sizing"]["risk_pct"] > cfg.get("risk.risk_per_trade_pct")
    # ...but the 2% open-risk cap still vetoes when the book is already loaded
    positions = [{"pair": "X/USDT", "sector": None, "risk_quote": 190.0}]
    v2 = risk.evaluate(hi_conv, state(open_positions=positions), cfg)
    assert v2["decision"] == "rejected"
    assert any(r.startswith("max_open_risk") for r in v2["reject_reasons"])


def test_conviction_never_breaks_concurrent_cap(cfg):
    hi_conv = {**proposal(), "conviction": 99}
    positions = [{"pair": f"P{i}/USDT", "sector": None, "risk_quote": 5}
                 for i in range(3)]
    v = risk.evaluate(hi_conv, state(open_positions=positions), cfg)
    assert any(r.startswith("max_concurrent") for r in v["reject_reasons"])


# ---- explicit volatility check (v3.2) ----
def test_volatility_extreme_rejects(cfg):
    v = risk.evaluate(proposal(), state(atr_percentile=99.0), cfg)
    assert v["decision"] == "rejected"
    assert any(r.startswith("volatility_extreme") for r in v["reject_reasons"])


def test_volatility_below_threshold_passes(cfg):
    v = risk.evaluate(proposal(), state(atr_percentile=60.0), cfg)
    assert v["decision"] == "accepted"


def test_volatility_unknown_never_blocks(cfg):
    v = risk.evaluate(proposal(), state(atr_percentile=None), cfg)
    assert v["decision"] == "accepted"
