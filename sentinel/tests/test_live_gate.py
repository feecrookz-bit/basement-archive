"""The paper->live gate: three independent locks, all must be open.
All 8 combinations tested — exactly one yields live."""
import itertools

import pytest

from sentinel import config as config_mod
from sentinel.modules.executor import resolve_mode


def make_cfg(live: bool):
    cfg = config_mod.Config({"mode": {"live": live, "min_paper_days": 30}}, "x")
    return cfg


@pytest.mark.parametrize("cfg_live,cli,days_ok", list(itertools.product(
    [False, True], [False, True], [False, True])))
def test_gate_matrix(cfg_live, cli, days_ok):
    days = 45 if days_ok else 12
    mode = resolve_mode(make_cfg(cfg_live), cli, days)
    if cfg_live and cli and days_ok:
        assert mode == "live"
    else:
        assert mode == "paper"


def test_default_config_is_paper():
    from pathlib import Path
    cfg = config_mod.load(Path(__file__).resolve().parent.parent / "config.yaml")
    # shipped default: even with CLI flag and history, config says paper
    assert resolve_mode(cfg, True, 999) == "paper"
