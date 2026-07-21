"""Conviction on the shared pipeline: two setups on one pair collapse to a
single conviction-ranked trade, sized up modestly, caps intact."""
import pytest

from sentinel.modules import conviction, expectancy, risk
from sentinel.modules.executor import Executor
from sentinel.bus import Bus
from sentinel.ledger import MemoryLedger


def prop(pair, setup, entry=100.0, stop=95.0, rr=2.0):
    return {"pair": pair, "setup_type": setup, "side": "long",
            "entry_price": entry, "stop_price": stop,
            "targets": [{"price": entry + rr * (entry - stop), "r_multiple": rr}],
            "evidence": {}, "id": 1}


@pytest.mark.asyncio
async def test_two_setups_one_pair_one_trade_sized_up(cfg):
    ledger = MemoryLedger()
    bus = Bus(redis=None, pool=None, persist=False)
    ex = Executor(ledger, bus, cfg, mode="backtest")

    # two setups fire on the same pair -> confluence
    proposals = [prop("SOL/USDT", "rs_momentum"), prop("SOL/USDT", "breakout_retest")]
    exp = await expectancy.setup_expectancy(ledger, cfg)  # cold-start neutral
    ranked = conviction.rank(proposals, exp, cfg)

    # exactly one primary proposal for the pair, with confluence conviction
    assert len(ranked) == 1
    p = ranked[0]
    assert set(p["agreeing_setups"]) == {"rs_momentum", "breakout_retest"}
    assert p["conviction"] > cfg.get("conviction.setup_base_weights")["rs_momentum"]

    # risk sizes it up (conviction > pivot) but within the envelope
    state = risk.AccountState(equity=10_000.0)
    verdict = await risk.judge(p, state, ledger, bus, cfg)
    assert verdict["decision"] == "accepted"
    assert verdict["sizing"]["risk_pct"] >= cfg.get("risk.risk_per_trade_pct")

    # one trade opens through the standard executor path
    await ex.on_accepted({"proposal": p, "sizing": verdict["sizing"]})
    assert len(ledger.trades) == 1
    assert ledger.trades[0]["pair"] == "SOL/USDT"


@pytest.mark.asyncio
async def test_ranking_prioritizes_high_conviction_under_slot_pressure(cfg):
    """With only 1 slot free, the highest-conviction pair wins it."""
    ledger = MemoryLedger()
    bus = Bus(redis=None, pool=None, persist=False)
    proposals = [prop("LOW/USDT", "range_play"),                 # weak single
                 prop("HIGH/USDT", "ict"),                        # ICT premium
                 prop("HIGH/USDT", "rs_momentum")]               # + confluence
    ranked = conviction.rank(proposals, {}, cfg)
    assert ranked[0]["pair"] == "HIGH/USDT"   # confluence+ICT ranks first

    # simulate 2 positions already open (1 slot left) -> only the top-ranked fills
    state = risk.AccountState(
        equity=10_000.0,
        open_positions=[{"pair": "A/USDT", "sector": None, "risk_quote": 5},
                        {"pair": "B/USDT", "sector": None, "risk_quote": 5}])
    accepted = []
    for p in ranked:
        v = await risk.judge(p, state, ledger, bus, cfg)
        if v["decision"] == "accepted":
            accepted.append(p["pair"])
            state.open_positions.append({"pair": p["pair"], "sector": None,
                                         "risk_quote": v["sizing"]["risk_quote"]})
    assert accepted == ["HIGH/USDT"]  # the best trade got the last slot
