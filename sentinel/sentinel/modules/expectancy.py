"""EXPECTANCY — the ledger self-tuner ("let the ledger decide").

Each setup earns trust from its own realized results. This reads the trailing
window of closed trades per setup, computes average R, and turns it into a
conviction multiplier used by conviction.py. Cold-start safe: below
`min_trades` a setup is NEUTRAL (1.0), so the system behaves as pure
confluence+ICT until the paper ledger has enough evidence, then self-tunes —
winners lead, losers fade toward the clamp floor (and get gated out).

Mirrors the tracker's wallet-weight philosophy: measured, bounded, automatic.
"""


def _mult(avg_r: float, n: int, cfg) -> float:
    lo, hi = cfg.get("conviction.expectancy.clamp", [0.25, 2.0])
    if n < cfg.get("conviction.expectancy.min_trades", 8):
        return 1.0  # neutral until proven
    k = cfg.get("conviction.expectancy.k", 0.6)
    return round(max(lo, min(hi, 1 + k * avg_r)), 4)


def from_results(results: list[dict], cfg) -> dict:
    """results: [{setup_type, r_result}] closed trades (any order).
    Returns {setup_type: multiplier}. Pure — the testable core."""
    window = cfg.get("conviction.expectancy.window_trades", 30)
    by_setup: dict[str, list[float]] = {}
    for t in results:
        by_setup.setdefault(t["setup_type"], []).append(t.get("r_result") or 0.0)
    out = {}
    for setup, rs in by_setup.items():
        recent = rs[-window:]
        avg = sum(recent) / len(recent) if recent else 0.0
        out[setup] = _mult(avg, len(recent), cfg)
    return out


async def setup_expectancy(ledger, cfg) -> dict:
    """Read closed-trade R by setup from whichever ledger is in use."""
    # MemoryLedger (tests/backtest): fold in-memory events.
    if hasattr(ledger, "trades") and isinstance(getattr(ledger, "trades"), list):
        results = []
        for t in ledger.trades:
            evs = [e for e in ledger.trade_events if e["trade_id"] == t["trade_id"]]
            if not any(e["type"] in ("CLOSED", "STOP_HIT", "TRAIL_HIT",
                                     "HALT_FLATTENED") for e in evs):
                continue
            rs = [e["r_at_event"] for e in evs if e.get("r_at_event") is not None]
            results.append({"setup_type": t["setup_type"],
                            "r_result": rs[-1] if rs else 0.0})
        return from_results(results, cfg)

    # PgLedger: closed trades' final R per setup.
    pool = getattr(ledger, "pool", None)
    if pool is None:
        return {}
    window = cfg.get("conviction.expectancy.window_trades", 30)
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT t.setup_type,
                   (SELECT r_at_event FROM trade_events e
                     WHERE e.trade_id = t.trade_id AND e.r_at_event IS NOT NULL
                     ORDER BY e.seq DESC LIMIT 1) AS r_result
            FROM trades t JOIN v_trade_state v USING (trade_id)
            WHERE v.is_closed
            ORDER BY t.opened_at DESC
            LIMIT $1
            """, window * 4)
    return from_results([{"setup_type": r["setup_type"],
                          "r_result": r["r_result"] or 0.0}
                         for r in reversed(rows)], cfg)
