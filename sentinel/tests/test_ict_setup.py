"""The composite ICT long setup — every stage of proof is mandatory."""
from sentinel.modules.ict import setup as ict_setup
from tests.conftest import candle, sweep_displacement_series


def sess_with_targets(high=106.0):
    """Closed asia session whose high sits above the entry = the target."""
    return {
        "current": "newyork",
        "asia": {"status": "closed", "high": high, "low": 100.0,
                 "high_swept": False, "low_swept": True},
        "london": {"status": "closed", "high": None, "low": None,
                   "high_swept": False, "low_swept": False},
        "newyork": {"status": "open", "high": None, "low": None,
                    "high_swept": False, "low_swept": False},
    }


def levels(pdh=107.0, pdl=100.0):
    return {"pdh": pdh, "pdl": pdl, "pwh": None, "pwl": None,
            "pdh_hit": False, "pdl_hit": False, "pwh_hit": False,
            "pwl_hit": False}


def flat_ref(n=200):
    return [candle(i, 100, 100.5, 99.5, 100.1) for i in range(n)]


def test_full_sequence_fires(cfg, watch_entry):
    series = sweep_displacement_series()
    p = ict_setup.detect(series, flat_ref(len(series)), sess_with_targets(),
                         levels(), watch_entry, cfg)
    assert p is not None
    ev = p["evidence"]
    assert ev["sweep"]["sweep_low"] < ev["sweep"]["level"]
    assert p["stop_price"] < ev["sweep"]["level"]      # stop below the swept level
    assert p["entry_price"] > p["stop_price"]
    assert ev["rr_first_target"] >= cfg.get("ict.min_rr", 2.0)
    assert p["targets"][0]["price"] > p["entry_price"]


def test_no_sweep_no_trade(cfg, watch_entry):
    series = sweep_displacement_series(do_sweep=False)
    assert ict_setup.detect(series, flat_ref(len(series)), sess_with_targets(),
                            levels(), watch_entry, cfg) is None


def test_no_displacement_no_trade(cfg, watch_entry):
    series = sweep_displacement_series(do_displace=False, retrace_to_ote=False)
    assert ict_setup.detect(series, flat_ref(len(series)), sess_with_targets(),
                            levels(), watch_entry, cfg) is None


def test_no_retrace_no_trade(cfg, watch_entry):
    """Displacement candle printed but price never came back to discount —
    buying here would be buying the breakout candle, which ICT forbids."""
    series = sweep_displacement_series(retrace_to_ote=False)
    assert ict_setup.detect(series, flat_ref(len(series)), sess_with_targets(),
                            levels(), watch_entry, cfg) is None


def test_rr_floor_rejects(cfg, watch_entry):
    """Nearest liquidity barely above entry -> R:R below floor -> no trade."""
    series = sweep_displacement_series()
    poor_sess = sess_with_targets(high=None)
    poor_sess["asia"]["high"] = None
    p = ict_setup.detect(series, flat_ref(len(series)), poor_sess,
                         levels(pdh=102.3), watch_entry, cfg)
    assert p is None


def test_long_only(cfg, watch_entry):
    series = sweep_displacement_series()
    p = ict_setup.detect(series, flat_ref(len(series)), sess_with_targets(),
                         levels(), watch_entry, cfg)
    assert p is None or p.get("side", "long") == "long"


def test_smt_flag_present_in_evidence(cfg, watch_entry):
    series = sweep_displacement_series()
    p = ict_setup.detect(series, flat_ref(len(series)), sess_with_targets(),
                         levels(), watch_entry, cfg)
    assert p is not None and "smt_divergence" in p["evidence"]
