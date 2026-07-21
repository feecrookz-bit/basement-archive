"""COACH — nightly/weekly reporting. The feedback loop that matters more
than any single trade: which setup and regime combinations actually earn.

Metrics are computed from the append-only ledger; the narrative is plain
English written for the human who has to decide whether the system has an
edge — not marketing copy.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

log = logging.getLogger("coach")


def metrics_from_trades(trades: list[dict]) -> dict:
    """trades: [{pair, setup_type, regime_state, r_result, pnl_quote, closed}]
    Pure — usable on any slice (period, setup, regime, pair)."""
    closed = [t for t in trades if t.get("closed")]
    if not closed:
        return {"trades": 0}
    rs = [t.get("r_result") or 0 for t in closed]
    pnls = [t.get("pnl_quote") or 0 for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    equity_curve, run = [], 0.0
    for p in pnls:
        run += p
        equity_curve.append(run)
    peak, max_dd = 0.0, 0.0
    for v in equity_curve:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return {
        "trades": len(closed),
        "win_rate": round(100 * len(wins) / len(closed), 1),
        "avg_r": round(sum(rs) / len(rs), 3),
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "profit_factor": round(sum(wins) / sum(losses), 2) if losses else None,
        "net_pnl_quote": round(sum(pnls), 2),
        "max_drawdown_quote": round(max_dd, 2),
    }


def build_report(trades: list[dict], rejected: list[dict], period: str) -> tuple[dict, str]:
    top = metrics_from_trades(trades)
    by = {}
    for key in ("setup_type", "regime_state", "pair"):
        groups = defaultdict(list)
        for t in trades:
            groups[t.get(key) or "unknown"].append(t)
        by[f"by_{key}"] = {k: metrics_from_trades(v) for k, v in groups.items()}
    reject_counts = defaultdict(int)
    for r in rejected:
        for reason in r.get("reject_reasons") or []:
            reject_counts[reason.split(":")[0]] += 1
    metrics = {**top, **by, "rejected_review": dict(reject_counts)}

    # plain-English narrative
    lines = []
    if not top.get("trades"):
        lines.append(f"No closed trades this {period}. Flat is the default state — "
                     f"that is the system working, not failing.")
    else:
        lines.append(
            f"{top['trades']} closed trades: {top['win_rate']}% wins, "
            f"avg {top['avg_r']:+.2f}R, net {top['net_pnl_quote']:+.2f} USDT "
            f"(PF {top['profit_factor']}).")
        best = max(by["by_setup_type"].items(),
                   key=lambda kv: kv[1].get("net_pnl_quote") or 0)
        worst = min(by["by_setup_type"].items(),
                    key=lambda kv: kv[1].get("net_pnl_quote") or 0)
        if best[1].get("trades"):
            lines.append(f"Best setup: {best[0]} "
                         f"({best[1]['net_pnl_quote']:+.2f} USDT over "
                         f"{best[1]['trades']}).")
        if worst[0] != best[0] and worst[1].get("trades"):
            lines.append(f"Worst setup: {worst[0]} "
                         f"({worst[1]['net_pnl_quote']:+.2f} USDT) — if this stays "
                         f"negative across regimes for weeks, disable it in config "
                         f"rather than tweaking it mid-drawdown.")
    if reject_counts:
        top_reason = max(reject_counts.items(), key=lambda kv: kv[1])
        lines.append(f"Risk vetoed {sum(reject_counts.values())} proposals "
                     f"(most common: {top_reason[0]} ×{top_reason[1]}). "
                     f"Rejections are the risk engine doing its job.")
    return metrics, " ".join(lines)


async def run_report(pool, ledger, period: str = "daily") -> None:
    days = 1 if period == "daily" else 7
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    async with pool.acquire() as con:
        trades = [dict(r) for r in await con.fetch(
            """
            SELECT t.trade_id, t.pair, t.setup_type, t.mode,
                   r.btc_state AS regime_state,
                   ts.is_closed AS closed,
                   ts.realized_pnl_quote AS pnl_quote,
                   (SELECT MAX(r_at_event) FROM trade_events e
                     WHERE e.trade_id = t.trade_id) AS r_result
            FROM trades t
            JOIN v_trade_state ts USING (trade_id)
            JOIN proposals p ON p.id = t.proposal_id
            JOIN regime_snapshots r ON r.id = p.regime_snapshot_id
            WHERE t.opened_at >= $1
            """, since)]
        rejected = [dict(r) for r in await con.fetch(
            "SELECT reject_reasons FROM proposal_decisions "
            "WHERE decision='rejected' AND ts >= $1", since)]
    metrics, narrative = build_report(trades, rejected, period)
    await ledger.insert_report(period, since, now, metrics, narrative)
    log.info("coach %s report: %s", period, narrative)
    from .. import notify
    await notify.send(title=f"🧭 Coach {period} report", body=narrative)
