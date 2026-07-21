from datetime import datetime, timezone

from sentinel.modules import scout


def test_rs_score_alt_outperforming(cfg):
    btc = [100.0 + 0.05 * i for i in range(100)]
    alt = [100.0 + 0.5 * i for i in range(100)]
    assert scout.rs_score(alt, btc, cfg) > 0
    assert scout.rs_score(btc, alt, cfg) < 0


def test_rs_score_insufficient_data(cfg):
    assert scout.rs_score([1.0, 2.0], [1.0, 2.0], cfg) is None


def test_higher_lows_vs_btc():
    btc = [100.0] * 90
    alt = [100.0 + i * 0.3 for i in range(90)]  # steadily strengthening ratio
    assert scout.higher_lows_vs_btc(alt, btc) is True
    weakening = [100.0 - i * 0.3 for i in range(90)]
    assert scout.higher_lows_vs_btc(weakening, btc) is False


def test_unlock_blacklist(cfg, tmp_path):
    csv = tmp_path / "unlocks.csv"
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    csv.write_text(
        "symbol,unlock_at,supply_pct\n"
        "ARB,2026-07-24T00:00:00Z,2.5\n"      # inside window, big -> blacklisted
        "OP,2026-07-24T00:00:00Z,0.4\n"       # inside window, small -> allowed
        "APT,2026-09-01T00:00:00Z,5.0\n"      # outside window -> allowed
        "OLD,2026-07-01T00:00:00Z,9.0\n"      # already passed -> allowed
    )
    cfg._tree.setdefault("scout", {}).setdefault("unlocks", {})["csv_path"] = str(csv)
    assert scout.load_unlocks(cfg, now) == {"ARB"}
