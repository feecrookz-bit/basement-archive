from pathlib import Path

from sentinel import config as config_mod

ROOT = Path(__file__).resolve().parent.parent


def test_loads_and_hashes():
    cfg = config_mod.load(ROOT / "config.yaml")
    assert cfg.content_hash and len(cfg.content_hash) == 64
    # same content -> same hash (deterministic canonicalization)
    again = config_mod.load(ROOT / "config.yaml")
    assert again.content_hash == cfg.content_hash


def test_defaults_match_prompt():
    cfg = config_mod.load(ROOT / "config.yaml")
    assert cfg.get("mode.live") is False           # paper is the default
    assert cfg.get("mode.min_paper_days") == 30
    assert cfg.get("risk.risk_per_trade_pct") == 0.75
    assert cfg.get("risk.max_concurrent_positions") == 3
    assert cfg.get("risk.max_total_open_risk_pct") == 2.0
    assert cfg.get("risk.circuit_breakers.daily_loss_pct") == 2.0
    assert cfg.get("risk.circuit_breakers.weekly_loss_pct") == 5.0
    assert cfg.get("risk.overtrading_governor.max_new_entries_per_24h") == 4
    assert cfg.get("regime.kill.btc_1h_move_pct") == 3.0
    assert cfg.get("scout.universe.min_24h_volume_usd") == 20_000_000
    assert cfg.get("fees_and_fills.taker_fee_pct") == 0.10
    assert cfg.get("analyst.setups.breakout_retest.never_buy_breakout_candle") is True


def test_dotted_get_missing_returns_default():
    cfg = config_mod.load(ROOT / "config.yaml")
    assert cfg.get("no.such.path", 42) == 42
