from sentinel.modules.analyst import range_play
from tests.conftest import flat_series, range_series


def test_detects_respected_range(cfg, watch_entry):
    p = range_play.detect(range_series(60), watch_entry, cfg)
    assert p is not None
    assert p["entry_price"] > p["stop_price"]
    assert p["targets"][0]["price"] > p["entry_price"]
    ev = p["evidence"]
    assert ev["low_touches"] >= 3 and ev["high_touches"] >= 3


def test_no_proposal_when_price_mid_range(cfg, watch_entry):
    series = range_series(60)
    # park price mid-range: setup exists but is not actionable
    mid = (series[-1]["low"] + 8)
    series[-1] = {**series[-1], "close": mid + 5, "high": mid + 6, "low": mid}
    assert range_play.detect(series, watch_entry, cfg) is None


def test_no_proposal_without_enough_touches(cfg, watch_entry):
    assert range_play.detect(flat_series(60, wobble=0.1), watch_entry, cfg) is None
