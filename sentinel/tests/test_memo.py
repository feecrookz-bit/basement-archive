"""Decision memos: status mapping, stars, risk rating, render."""
from sentinel.modules import memo


class Cfg(dict):
    def get(self, key, default=None):
        return super().get(key, default)


CFG = Cfg({"risk.risk_per_trade_pct": 0.75})

PROPOSAL = {
    "pair": "SOL/USDT", "setup_type": "ict", "side": "long",
    "entry_price": 100.0, "stop_price": 98.0,
    "targets": [{"price": 105.0, "r_multiple": 2.5}],
    "evidence": {"conviction": 2.6, "agreeing_setups": ["ict", "rs_momentum"],
                 "rr_first_target": 2.5},
}


def _verdict(decision="accepted", reasons=None, risk_pct=0.9):
    sizing = None if decision == "rejected" else \
        {"qty": 1, "risk_quote": 90, "risk_pct": risk_pct}
    return {"decision": decision, "reject_reasons": reasons, "sizing": sizing}


def test_approved_status_and_fields():
    m = memo.compose(PROPOSAL, _verdict(), CFG)
    assert m["status"] == "APPROVED"
    assert m["plan"] == {"entry": 100.0, "stop": 98.0, "target": 105.0, "rr": 2.5}
    assert m["signal"]["stars"] == 5  # conviction 2.6 >= 2.5
    assert m["signal"]["agreeing_setups"] == ["ict", "rs_momentum"]


def test_capacity_rejections_become_watchlist():
    for reason in ["max_concurrent:3", "sector_cap:L1",
                   "overtrading_governor:4/24h", "max_open_risk:2.1>2.0",
                   "already_in_pair"]:
        v = _verdict("rejected", [reason])
        assert memo.status_of(v) == "WATCHLIST", reason


def test_quality_rejections_stay_rejected():
    for reason in ["daily_breaker:-2.5%", "weekly_breaker:-5.1%",
                   "halt_active", "invalid_entry_stop",
                   "volatility_extreme:99pctile"]:
        v = _verdict("rejected", [reason])
        assert memo.status_of(v) == "REJECTED", reason
    # a mix containing any quality fail is REJECTED, not WATCHLIST
    v = _verdict("rejected", ["sector_cap:L1", "volatility_extreme:99pctile"])
    assert memo.status_of(v) == "REJECTED"


def test_stars_scale():
    assert memo.stars(None) == 3
    assert memo.stars(0.4) == 1
    assert memo.stars(1.0) == 2
    assert memo.stars(1.5) == 3
    assert memo.stars(2.0) == 4
    assert memo.stars(3.5) == 5


def test_risk_rating():
    assert memo.risk_rating({"risk_pct": 0.6}, CFG) == "LOW"
    assert memo.risk_rating({"risk_pct": 0.75}, CFG) == "MODERATE"
    assert memo.risk_rating({"risk_pct": 1.1}, CFG) == "ELEVATED"
    assert memo.risk_rating(None, CFG) == "MODERATE"  # base risk fallback


def test_render_text_contains_verdict_and_plan():
    m = memo.compose(PROPOSAL, _verdict("rejected", ["sector_cap:L1"]), CFG)
    text = memo.render_text(m)
    assert "WATCHLIST" in text and "SOL/USDT" in text
    assert "sector_cap:L1" in text and "entry 100.0" in text
