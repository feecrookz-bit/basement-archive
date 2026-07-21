"""Kill-zone discipline: window math, macro windows, gating, golden bonus."""
from datetime import datetime, timezone

from sentinel.modules.ict import killzone as kz


class Cfg(dict):
    def get(self, key, default=None):
        return super().get(key, default)


CFG = Cfg()  # defaults: london 07:00-10:00, ny_am 13:30-15:00 UTC


def at(h, m=0):
    return datetime(2026, 7, 21, h, m, tzinfo=timezone.utc)


def test_london_kz_active_with_macro_windows():
    s = kz.state(at(7, 5), CFG)
    assert s == {"active": True, "zone": "london", "macro_window": "macro1",
                 "next_open_utc": None}
    assert kz.state(at(7, 45), CFG)["macro_window"] == "golden"
    assert kz.state(at(9, 10), CFG)["macro_window"] == "macro3"
    assert kz.state(at(8, 30), CFG)["macro_window"] is None  # KZ, no macro


def test_ny_am_kz_and_dead_hours():
    assert kz.state(at(14, 0), CFG)["zone"] == "ny_am"
    dead = kz.state(at(20, 0), CFG)
    assert dead["active"] is False and dead["zone"] is None
    assert dead["next_open_utc"] == "07:00"  # tomorrow's London
    # between London close and NY-AM open, next open is 13:30 today
    assert kz.state(at(11, 0), CFG)["next_open_utc"] == "13:30"


def test_window_boundaries_are_half_open():
    assert kz.state(at(7, 0), CFG)["active"] is True     # start inclusive
    assert kz.state(at(10, 0), CFG)["active"] is False   # end exclusive


def test_midnight_wrap():
    cfg = Cfg({"ict.killzones.windows":
               {"overnight": {"start": "23:00", "end": "01:00"}}})
    assert kz.state(at(23, 30), cfg)["zone"] == "overnight"
    assert kz.state(at(0, 30), cfg)["zone"] == "overnight"
    assert kz.state(at(2, 0), cfg)["active"] is False


def test_entries_allowed_gate():
    assert kz.entries_allowed(at(8, 0), CFG) is True
    assert kz.entries_allowed(at(20, 0), CFG) is False
    off = Cfg({"ict.killzones.enabled": False})
    assert kz.entries_allowed(at(20, 0), off) is True  # opt-out = 24/7


def test_golden_multiplier():
    ev_golden = {"killzone": {"macro_window": "golden"}}
    ev_other = {"killzone": {"macro_window": "macro1"}}
    assert kz.golden_multiplier(ev_golden, CFG) == 1.15
    assert kz.golden_multiplier(ev_other, CFG) == 1.0
    assert kz.golden_multiplier({}, CFG) == 1.0
    # bonus is clamped to a sane ceiling
    greedy = Cfg({"ict.killzones.golden_bonus": 5.0})
    assert kz.golden_multiplier(ev_golden, greedy) == 1.5
    off = Cfg({"ict.killzones.enabled": False})
    assert kz.golden_multiplier(ev_golden, off) == 1.0
