"""
Paper-trading ledger — proof of edge before money.

Every gated signal opens a hypothetical position at the checked price. A
background monitor re-prices open positions every PAPER_CHECK_SECONDS and
closes them at take-profit, stop-loss, timeout, or 'dead' (pair vanished =
rug; recorded as -100%, because that is what would have happened).

PnL is net of ASSUMED_SLIPPAGE_PCT round-trip — meme pools punish size, and
a ledger that ignores slippage is fiction.

Outcomes feed back into wallet quality: the trigger wallet's weight moves up
on wins and down on losses, bounded 0.25–3.0. Wallets that keep triggering
losers get muted by the scoring automatically.
"""
import asyncio
import logging
from datetime import datetime, timezone

from . import config, db, enrich, notify

log = logging.getLogger("paper")

async def open_trade(signal_id: int, token: str, wallet: str, price: float,
                     kind: str = "momentum") -> None:
    async with db.pool().acquire() as con:
        exists = await con.fetchval(
            "SELECT 1 FROM paper_trades WHERE token_address=$1 AND kind=$2 "
            "AND status='open'", token, kind)
        if exists:
            return  # one open position per token per kind
        await con.execute(
            "INSERT INTO paper_trades (signal_id, token_address, trigger_wallet, "
            "entry_price, stake_sol, peak_price, kind, peak_x) "
            "VALUES ($1,$2,$3,$4,$5,$4,$6,1.0)",
            signal_id, token, wallet, price, config.PAPER_STAKE_SOL, kind,
        )
    log.info("paper OPEN [%s] %s @ %.10f", kind, token[:8], price)

async def _close(con, trade, price: float | None, status: str) -> None:
    entry = trade["entry_price"]
    if price is None or entry <= 0:
        pnl = -100.0
    else:
        gross = 100 * (price - entry) / entry
        pnl = round(gross - config.ASSUMED_SLIPPAGE_PCT, 2)
    await con.execute(
        "UPDATE paper_trades SET exit_price=$1, pnl_pct=$2, status=$3, closed_at=now() "
        "WHERE id=$4", price, pnl, status, trade["id"],
    )

    # ---- feed outcome back into wallet quality ----
    win = pnl > 0
    delta = 0.15 if win else -0.15
    await con.execute(
        """
        UPDATE tracked_wallets SET
            weight = GREATEST(0.25, LEAST(3.0, weight + $1)),
            wins   = wins + $2,
            losses = losses + $3
        WHERE wallet = $4
        """,
        delta, int(win), int(not win), trade["trigger_wallet"],
    )
    emoji = {"tp": "🟢", "sl": "🔴", "timeout": "⏱️", "dead": "💀"}[status]
    kind = trade.get("kind") or "momentum"
    peak = trade.get("peak_x")
    peak_note = f" | peak {peak:.1f}x" if peak and kind == "moonshot" else ""
    log.info("paper CLOSE [%s] %s %s %+.1f%%", kind, trade["token_address"][:8], status, pnl)
    await notify.send(
        title=f"{emoji} Paper [{kind}] {status.upper()} {pnl:+.1f}%",
        body=(f"{trade['token_address'][:10]}… entry {entry:.10f} exit "
              f"{price if price else 0:.10f}{peak_note} | "
              f"trigger {trade['trigger_wallet'][:6]}…"),
    )

async def monitor() -> None:
    """Background loop: re-price open paper trades, enforce TP/SL/timeout."""
    if not config.PAPER_ENABLED:
        return
    while True:
        try:
            async with db.pool().acquire() as con:
                open_trades = await con.fetch(
                    "SELECT * FROM paper_trades WHERE status='open'")
            for t in open_trades:
                price = await enrich.current_price(t["token_address"])
                now = datetime.now(timezone.utc)
                age_h = (now - t["opened_at"]).total_seconds() / 3600
                async with db.pool().acquire() as con:
                    if price is None:
                        # give a young pair a grace period for indexer lag
                        if age_h > 0.5:
                            await _close(con, t, None, "dead")
                        continue
                    if price > (t["peak_price"] or 0):
                        await con.execute(
                            "UPDATE paper_trades SET peak_price=$1, peak_x=$2 WHERE id=$3",
                            price, round(price / t["entry_price"], 2), t["id"])
                    chg = 100 * (price - t["entry_price"]) / t["entry_price"]
                    if (t.get("kind") or "momentum") == "moonshot":
                        # no take-profit: the whole point is measuring the run.
                        if chg <= -config.MOONSHOT_SL_PCT:
                            await _close(con, t, price, "sl")
                        elif age_h >= config.MOONSHOT_TIMEOUT_HOURS:
                            await _close(con, t, price, "timeout")
                    elif chg >= config.PAPER_TP_PCT:
                        await _close(con, t, price, "tp")
                    elif chg <= -config.PAPER_SL_PCT:
                        await _close(con, t, price, "sl")
                    elif age_h >= config.PAPER_TIMEOUT_HOURS:
                        await _close(con, t, price, "timeout")
        except Exception as e:  # noqa: BLE001
            log.warning("paper monitor error: %s", e)
        await asyncio.sleep(config.PAPER_CHECK_SECONDS)

async def ledger_summary() -> dict:
    out: dict = {}
    async with db.pool().acquire() as con:
        for kind in ("momentum", "moonshot"):
            row = await con.fetchrow(
                """
                SELECT COUNT(*) FILTER (WHERE status <> 'open')              AS closed,
                       COUNT(*) FILTER (WHERE status = 'open')               AS open,
                       COUNT(*) FILTER (WHERE pnl_pct > 0)                   AS wins,
                       COALESCE(SUM(pnl_pct * stake_sol / 100.0), 0)         AS net_sol,
                       COALESCE(AVG(pnl_pct) FILTER (WHERE status<>'open'),0) AS avg_pnl_pct,
                       MAX(peak_x)                                           AS best_peak_x
                FROM paper_trades WHERE kind = $1
                """, kind)
            d = dict(row)
            d["win_rate"] = round(100 * d["wins"] / d["closed"], 1) if d["closed"] else None
            d["net_sol"] = round(d["net_sol"], 3)
            d["avg_pnl_pct"] = round(d["avg_pnl_pct"], 1)
            out[kind] = d
    # combined topline for the dashboard strip
    out["net_sol"] = round(out["momentum"]["net_sol"] + out["moonshot"]["net_sol"], 3)
    out["closed"] = out["momentum"]["closed"] + out["moonshot"]["closed"]
    out["open"] = out["momentum"]["open"] + out["moonshot"]["open"]
    wins = out["momentum"]["wins"] + out["moonshot"]["wins"]
    out["win_rate"] = round(100 * wins / out["closed"], 1) if out["closed"] else None
    return out
