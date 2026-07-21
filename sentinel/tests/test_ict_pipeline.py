"""End-to-end: the ICT agent runs inside the production analyst pass
(ReplayMarket + MemoryLedger), its proposal is judged by risk, and the
executor opens the paper trade — the same code path live uses."""
import pytest

from sentinel.bus import Bus
from sentinel.data.market import ReplayMarket
from sentinel.ledger import MemoryLedger
from sentinel.modules import analyst, conviction, expectancy, risk
from sentinel.modules.executor import Executor
from tests.conftest import candle, sweep_displacement_series

HOUR = 3_600_000
DAY0 = 1_700_006_400_000  # midnight UTC


def fixture_series():
    alt_15m = sweep_displacement_series(n_range=60, low=100.0, high=103.0,
                                        start=DAY0)
    btc_15m = [candle(DAY0 + i * 900_000, 100, 100.5, 99.5, 100.1)
               for i in range(len(alt_15m))]
    # yesterday's 1h candles -> PDH 107 / PDL 99
    alt_1h = [candle(DAY0 - 24 * HOUR + h * HOUR, 102,
                     107 if h == 10 else 103, 99 if h == 5 else 101, 102)
              for h in range(24)]
    # today's 1h so far (flat, no level hits)
    alt_1h += [candle(DAY0 + h * HOUR, 101, 102, 100, 101) for h in range(15)]
    return {
        ("ALT/USDT", "15m"): alt_15m,
        ("BTC/USDT", "15m"): btc_15m,
        ("ALT/USDT", "1h"): alt_1h,
        ("BTC/USDT", "1h"): alt_1h,
    }


@pytest.mark.asyncio
async def test_ict_flows_through_analyst_risk_executor(cfg):
    cfg._tree.setdefault("ict", {})["min_rr"] = 1.0  # fixture targets are close
    series = fixture_series()
    market = ReplayMarket(series)
    market.set_now_ms(series[("ALT/USDT", "15m")][-1]["ts"])
    ledger = MemoryLedger()
    bus = Bus(redis=None, pool=None, persist=False)

    regime_snap = {"id": await ledger.insert_regime(
        {"btc_state": "RANGING", "trading_allowed": True}),
        "trading_allowed": True}
    watchlist = {"id": await ledger.insert_watchlist(
        [{"pair": "ALT/USDT", "rs_score": 1.0, "rank": 1, "rs_decile": 5,
          "vol_24h_usd": 50_000_000, "spread_pct": 0.05,
          "flags": {"unlock_blacklist": False}}], 1, None),
        "entries": [{"pair": "ALT/USDT", "rs_score": 1.0, "rank": 1,
                     "rs_decile": 5, "vol_24h_usd": 50_000_000,
                     "spread_pct": 0.05, "flags": {"unlock_blacklist": False}}]}

    proposals = await analyst.scan(market, ledger, bus, cfg, regime_snap, watchlist)
    ict_props = [p for p in proposals if p["setup_type"] == "ict"]
    assert ict_props, "ICT setup did not fire on the fixture"
    p = ict_props[0]

    # ict snapshot read model was written
    assert getattr(ledger, "ict_snapshots", []) and \
        ledger.ict_snapshots[0]["pair"] == "ALT/USDT"

    # risk sizes it off the stop distance and accepts
    state = risk.AccountState(equity=10_000.0)
    verdict = await risk.judge(p, state, ledger, bus, cfg)
    assert verdict["decision"] == "accepted"
    assert verdict["sizing"]["risk_quote"] == 75.0   # 0.75% of 10k

    # executor opens the paper trade through the standard path
    ex = Executor(ledger, bus, cfg, mode="paper")
    await ex.on_accepted({"proposal": p, "sizing": verdict["sizing"]})
    assert ledger.trades and ledger.trades[0]["setup_type"] == "ict"
    opened = [e for e in ledger.trade_events if e["type"] == "OPENED"]
    assert len(opened) == 1 and opened[0]["fees_quote"] > 0


@pytest.mark.asyncio
async def test_ict_disabled_produces_nothing(cfg):
    cfg._tree.setdefault("ict", {})["enabled"] = False
    market = ReplayMarket(fixture_series())
    ledger = MemoryLedger()
    bus = Bus(redis=None, pool=None, persist=False)
    regime_snap = {"id": await ledger.insert_regime(
        {"btc_state": "RANGING", "trading_allowed": True}),
        "trading_allowed": True}
    props = await analyst.scan(market, ledger, bus, cfg, regime_snap,
                               {"id": 1, "entries": [{"pair": "ALT/USDT",
                                "flags": {}, "rs_decile": 5}]})
    assert [p for p in props if p["setup_type"] == "ict"] == []