from sentinel.modules import conviction


def prop(pair, setup, entry=100.0, stop=95.0, rr=2.0, ev=None):
    return {"pair": pair, "setup_type": setup, "entry_price": entry,
            "stop_price": stop, "targets": [{"price": entry + rr * (entry - stop),
                                             "r_multiple": rr}],
            "evidence": ev or {}}


def test_confluence_raises_score(cfg):
    one = conviction.score(["rs_momentum"], {}, cfg)
    two = conviction.score(["rs_momentum", "breakout_retest"], {}, cfg)
    assert two > one


def test_ict_premium(cfg):
    non_ict = conviction.score(["rs_momentum"], {}, cfg)
    ict = conviction.score(["ict"], {}, cfg)
    assert ict > non_ict  # ICT base weight 1.5 + premium 1.25


def test_expectancy_weights_score(cfg):
    trusted = conviction.score(["rs_momentum"], {"rs_momentum": 2.0}, cfg)
    doubted = conviction.score(["rs_momentum"], {"rs_momentum": 0.3}, cfg)
    assert trusted > doubted


def test_rank_orders_by_conviction(cfg):
    props = [prop("A/USDT", "range_play"),
             prop("B/USDT", "ict"),
             prop("C/USDT", "rs_momentum"), prop("C/USDT", "breakout_retest")]
    ranked = conviction.rank(props, {}, cfg)
    # one primary per pair
    assert sorted(p["pair"] for p in ranked) == ["A/USDT", "B/USDT", "C/USDT"]
    # strictly descending conviction
    convs = [p["conviction"] for p in ranked]
    assert convs == sorted(convs, reverse=True)
    # C (confluence of 2) and B (ICT) beat A (single low-weight range)
    a = next(p for p in ranked if p["pair"] == "A/USDT")
    assert ranked[0]["conviction"] > a["conviction"]


def test_primary_prefers_ict_entry(cfg):
    props = [prop("X/USDT", "rs_momentum", entry=100, stop=95),
             prop("X/USDT", "ict", entry=101, stop=99)]
    ranked = conviction.rank(props, {}, cfg)
    x = next(p for p in ranked if p["pair"] == "X/USDT")
    assert x["setup_type"] == "ict"        # ICT wins the entry/stop
    assert set(x["agreeing_setups"]) == {"ict", "rs_momentum"}


def test_primary_best_rr_when_no_ict(cfg):
    props = [prop("Y/USDT", "range_play", rr=1.5),
             prop("Y/USDT", "breakout_retest", rr=3.0)]
    ranked = conviction.rank(props, {}, cfg)
    y = next(p for p in ranked if p["pair"] == "Y/USDT")
    assert y["setup_type"] == "breakout_retest"  # best R:R


def test_negative_expectancy_setup_dropped(cfg):
    # range_play muted to the clamp floor -> excluded from agreeing set
    floor = cfg.get("conviction.expectancy.clamp")[0]
    props = [prop("Z/USDT", "range_play"), prop("Z/USDT", "rs_momentum")]
    ranked = conviction.rank(props, {"range_play": floor}, cfg)
    z = next(p for p in ranked if p["pair"] == "Z/USDT")
    assert "range_play" not in z["agreeing_setups"]
    assert "rs_momentum" in z["agreeing_setups"]


def test_never_drops_last_setup(cfg):
    floor = cfg.get("conviction.expectancy.clamp")[0]
    props = [prop("W/USDT", "range_play")]
    ranked = conviction.rank(props, {"range_play": floor}, cfg)
    w = next(p for p in ranked if p["pair"] == "W/USDT")
    assert w["agreeing_setups"] == ["range_play"]  # kept, reduced conviction


def test_disabled_passthrough(cfg):
    cfg._tree.setdefault("conviction", {})["enabled"] = False
    props = [prop("A/USDT", "ict"), prop("B/USDT", "range_play")]
    ranked = conviction.rank(props, {}, cfg)
    assert len(ranked) == 2 and all(p.get("conviction") == 1.0 for p in ranked)
