"""
Moonshot signal class — low-MC accumulation, not momentum.

Philosophy: a genuine 100x candidate at $50k–$1.5M FDV rarely looks hot. It
looks like smart wallets quietly adding over days while volume stays modest.
So the gates here are SURVIVAL-shaped (can this thing exist in 6 months?)
and the trigger is ACCUMULATION-shaped (repeated buys spread over time),
deliberately opposite to the momentum path in signals.py.

Gates (all must pass, on top of mint/freeze revoked):
  - FDV within [MOONSHOT_MIN_FDV, MOONSHOT_MAX_FDV]
  - liquidity >= MOONSHOT_MIN_LIQ_USD AND >= MOONSHOT_MIN_LIQ_PCT_FDV % of FDV
    (thin liq relative to mcap is the classic slow-rug setup)
  - top-10 holders <= MOONSHOT_MAX_TOP10_PCT %

Trigger (accumulation pattern over MOONSHOT_ACCUM_WINDOW_HOURS):
  - >= MOONSHOT_MIN_BUY_EVENTS tracked-wallet buys of >= MOONSHOT_MIN_BUY_SOL
  - first-to-last buy span >= MOONSHOT_MIN_ACCUM_SPAN_HOURS
    (one wallet adding 3x over 2 days = conviction; 3 buys in one block = a bundle)

Score = Σ(wallet_weight per distinct wallet) + 0.5 per extra buy event,
scaled by band position (lower FDV in band = more room = slightly higher).
"""
import logging

from . import config, db, notify

log = logging.getLogger("moonshot")


def gate(check: dict) -> list[str]:
    """Moonshot-specific gate failures (mint/freeze handled by caller's check)."""
    fails: list[str] = []
    fdv = check.get("fdv_usd") or 0
    liq = check.get("liquidity_usd") or 0
    top10 = check.get("top10_pct")
    if not fdv:
        fails.append("no FDV data")
    elif not (config.MOONSHOT_MIN_FDV <= fdv <= config.MOONSHOT_MAX_FDV):
        fails.append(f"FDV ${fdv:,.0f} outside "
                     f"[${config.MOONSHOT_MIN_FDV:,.0f}, ${config.MOONSHOT_MAX_FDV:,.0f}]")
    if liq < config.MOONSHOT_MIN_LIQ_USD:
        fails.append(f"liq ${liq:,.0f} < ${config.MOONSHOT_MIN_LIQ_USD:,.0f}")
    if fdv and liq and 100 * liq / fdv < config.MOONSHOT_MIN_LIQ_PCT_FDV:
        fails.append(f"liq/FDV {100*liq/fdv:.1f}% < {config.MOONSHOT_MIN_LIQ_PCT_FDV}% (slow-rug shape)")
    if check.get("mint_revoked") is False:
        fails.append("mint authority NOT revoked")
    if check.get("freeze_revoked") is False:
        fails.append("freeze authority NOT revoked")
    if top10 is not None and top10 > config.MOONSHOT_MAX_TOP10_PCT:
        fails.append(f"top-10 {top10}% > {config.MOONSHOT_MAX_TOP10_PCT}%")
    return fails


async def accumulation(con, token: str) -> dict | None:
    """Detect the accumulation pattern; None if not met."""
    rows = await con.fetch(
        f"""
        SELECT h.wallet, h.ts, h.sol_amount, COALESCE(w.weight, 1.0) AS weight
        FROM wallet_hits h
        LEFT JOIN tracked_wallets w ON w.wallet = h.wallet
        WHERE h.token_address = $1 AND h.side = 'buy'
          AND COALESCE(h.sol_amount, 0) >= $2
          AND h.ts > now() - interval '{config.MOONSHOT_ACCUM_WINDOW_HOURS} hours'
        ORDER BY h.ts
        """,
        token, config.MOONSHOT_MIN_BUY_SOL,
    )
    if len(rows) < config.MOONSHOT_MIN_BUY_EVENTS:
        return None
    span_h = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() / 3600
    if span_h < config.MOONSHOT_MIN_ACCUM_SPAN_HOURS:
        return None  # burst, not accumulation (likely bundled)
    wallets = {}
    for r in rows:
        wallets.setdefault(r["wallet"], r["weight"])
    return {"events": len(rows), "wallets": len(wallets),
            "span_h": round(span_h, 1),
            "weight_sum": sum(wallets.values()),
            "total_sol": round(sum(r["sol_amount"] or 0 for r in rows), 2)}


async def evaluate(token: str, chain_id: str, age_hours: float,
                   check: dict, trigger_wallet: str) -> None:
    """Called from signals.on_wallet_hit for buys within the moonshot window."""
    fails = gate(check)

    async with db.pool().acquire() as con:
        accum = await accumulation(con, token)
        if accum is None:
            return  # pattern not formed yet; stay silent, no row spam

        # don't re-fire while an open moonshot paper trade exists for this token
        already = await con.fetchval(
            "SELECT 1 FROM paper_trades WHERE token_address=$1 AND kind='moonshot' "
            "AND status='open'", token)
        if already:
            return

        fdv = check.get("fdv_usd") or config.MOONSHOT_MAX_FDV
        band = max(0.0, min(1.0, 1 - (fdv - config.MOONSHOT_MIN_FDV)
                            / (config.MOONSHOT_MAX_FDV - config.MOONSHOT_MIN_FDV)))
        score = round((accum["weight_sum"] + 0.5 * (accum["events"] - accum["wallets"]))
                      * (1 + 0.3 * band), 3)
        gated = not fails
        reason = (
            f"MOONSHOT: {accum['events']} buys / {accum['wallets']} wallet(s) over "
            f"{accum['span_h']}h ({accum['total_sol']} SOL total), "
            f"FDV ${fdv:,.0f}, liq ${check.get('liquidity_usd') or 0:,.0f}, "
            f"top10 {check.get('top10_pct') or '?'}%"
        )
        if not gated:
            reason += f" | GATED OUT: {'; '.join(fails)}"

        sig_id = await con.fetchval(
            "INSERT INTO signals (chain_id, token_address, wallet, reason, score, gated, kind) "
            "VALUES ($1,$2,$3,$4,$5,$6,'moonshot') RETURNING id",
            chain_id, token, trigger_wallet, reason, score, gated,
        )

    if not gated:
        log.info("moonshot filtered %s: %s", token[:8], "; ".join(fails))
        return

    log.info("MOONSHOT score=%s %s", score, token[:8])
    await notify.send(
        title=f"🌙 Moonshot {score} — accumulation detected",
        body=f"{reason}\nhttps://dexscreener.com/{chain_id}/{token}",
    )
    if config.PAPER_ENABLED and check.get("price_usd"):
        from . import paper
        await paper.open_trade(sig_id, token, trigger_wallet,
                               check["price_usd"], kind="moonshot")
