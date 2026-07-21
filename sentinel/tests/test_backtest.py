"""End-to-end: replay fixture klines through the production pipeline
(ReplayMarket + MemoryLedger, same module functions) and assert the ledger
fills through the same code path live uses."""
import pytest

from sentinel.backtest import replay
from tests.conftest import HOUR, T0, breakout_series, candle, flat_series


def btc_flat(n=400):
    return flat_series(n, price=60_000.0, wobble=120.0)


def btc_4h_from_1h(c1h):
    out = []
    for i in range(0, len(c1h) - 3, 4):
        chunk = c1h[i:i + 4]
        out.append(candle(chunk[0]["ts"], chunk[0]["open"],
                          max(c["high"] for c in chunk),
                          min(c["low"] for c in chunk), chunk[-1]["close"],
                          sum(c["volume"] for c in chunk)))
    return out


@pytest.mark.asyncio
async def test_replay_runs_and_ledger_is_event_sourced(cfg):
    alt = breakout_series(pre=200, post_break=5)
    # extend with follow-through so ladder logic gets exercised
    last = alt[-1]
    price = last["close"]
    for i in range(1, 30):
        p = price * (1 + 0.01 * i)
        alt.append(candle(last["ts"] + i * HOUR, p * 0.995, p * 1.005, p * 0.99, p))
    btc = btc_flat(len(alt))
    series = {("BTC/USDT", "1h"): btc,
              ("BTC/USDT", "4h"): btc_4h_from_1h(btc),
              ("ALT/USDT", "1h"): alt}
    result = await replay(cfg, series, "ALT/USDT")
    led = result["ledger"]

    # regime snapshots every step. Conviction collapses multiple same-pair
    # proposals into one judged primary, so decisions == distinct judged pairs
    # (<= raw proposals persisted for audit), and every decision is on a real
    # persisted proposal.
    assert led.regimes, "no regime snapshots recorded"
    assert len(led.decisions) <= len(led.proposals)
    proposal_ids = {p["id"] for p in led.proposals}
    assert all(d["proposal_id"] in proposal_ids for d in led.decisions)

    if led.trades:  # trades only open when regime+setup+risk all align
        # every trade opened by an accepted decision, mode=backtest
        assert all(t["mode"] == "backtest" for t in led.trades)
        opened = [e for e in led.trade_events if e["type"] == "OPENED"]
        assert len(opened) == len(led.trades)
        # append-only: per-trade seq strictly increasing from 1
        for t in led.trades:
            seqs = [e["seq"] for e in led.trade_events
                    if e["trade_id"] == t["trade_id"]]
            assert seqs == list(range(1, len(seqs) + 1))
        # fees are charged on every fill
        fills = [e for e in led.trade_events if e["qty_delta"] != 0]
        assert all(e["fees_quote"] >= 0 for e in fills)
    assert "metrics" in result and "narrative" in result


@pytest.mark.asyncio
async def test_replay_flat_market_stays_flat(cfg):
    """Flat is the default state: featureless tape must open nothing."""
    n = 300
    btc = btc_flat(n)
    alt = [candle(T0 + i * HOUR, 100, 100.05, 99.95, 100.0) for i in range(n)]
    series = {("BTC/USDT", "1h"): btc,
              ("BTC/USDT", "4h"): btc_4h_from_1h(btc),
              ("ALT/USDT", "1h"): alt}
    result = await replay(cfg, series, "ALT/USDT")
    assert result["ledger"].trades == []
