"""
Signal engine v2 — gated, weighted, exit-aware.

Pipeline on every tracked-wallet BUY:
  1. Token must be *fresh* in discovery (first_seen within FRESH_HOURS).
  2. Buy must clear MIN_BUY_SOL (dust = noise).
  3. Token must pass ALL safety gates in enrich.check_token()
     (liquidity, volume, FDV ceiling, mint/freeze revoked, holder concentration).
  4. Score = sum of wallet-quality weights of distinct buyers, boosted by
     confluence (several buyers within 30 min) and freshness, scaled by
     conviction (log of SOL size).
  5. Score >= MIN_SIGNAL_SCORE -> alert + open a paper trade.

On every tracked-wallet SELL of a token we've signalled: exit alert.
Wallet weights are auto-tuned by paper-trade outcomes (see paper.py).
"""
import logging
import math

from . import config, db, enrich, notify

log = logging.getLogger("signals")

async def _score(con, token: str) -> tuple[float, int, int]:
    """(score, distinct_buyers, confluence_buyers_30m)"""
    rows = await con.fetch(
        """
        SELECT DISTINCT ON (h.wallet) h.wallet, h.sol_amount, h.ts,
               COALESCE(w.weight, 1.0) AS weight
        FROM wallet_hits h
        LEFT JOIN tracked_wallets w ON w.wallet = h.wallet
        WHERE h.token_address = $1 AND h.side = 'buy'
        ORDER BY h.wallet, h.ts ASC
        """,
        token,
    )
    if not rows:
        return 0.0, 0, 0
    latest = max(r["ts"] for r in rows)
    confluence = sum(1 for r in rows if (latest - r["ts"]).total_seconds() <= 1800)
    score = 0.0
    for r in rows:
        conviction = 1 + 0.3 * math.log1p(max(r["sol_amount"] or 0, 0))  # 1 SOL≈1.2, 10 SOL≈1.7
        score += r["weight"] * conviction
    if confluence >= 2:
        score *= 1 + 0.25 * (confluence - 1)   # confluence multiplier
    return round(score, 3), len(rows), confluence

async def on_wallet_hit(hit: dict) -> None:
    token, wallet, side = hit["token_address"], hit["wallet"], hit["side"]

    async with db.pool().acquire() as con:
        tok = await con.fetchrow(
            """
            SELECT chain_id, source,
                   EXTRACT(EPOCH FROM (now() - first_seen)) / 3600 AS age_hours
            FROM tokens WHERE token_address = $1
            """,
            token,
        )

        # ---- Exit alert: smart money leaving something we signalled ----
        if side == "sell":
            was_signalled = await con.fetchval(
                "SELECT 1 FROM signals WHERE token_address=$1 AND gated LIMIT 1", token)
            if was_signalled:
                await notify.send(
                    title="🚪 Exit — tracked wallet selling",
                    body=(f"Wallet {wallet[:6]}… sold {token[:8]}… "
                          f"({hit.get('sol_amount') or '?'} SOL)\n"
                          f"https://dexscreener.com/solana/{token}"),
                )
            return

        # ---- Buy path ----
        if not tok or tok["age_hours"] is None:
            return  # not a discovery token
        in_momentum = tok["age_hours"] <= config.FRESH_HOURS
        in_moonshot = (config.MOONSHOT_ENABLED
                       and tok["age_hours"] <= config.MOONSHOT_FRESH_HOURS)
        if not in_momentum and not in_moonshot:
            return  # stale for both signal classes

    # ---- Safety data (outside the con: does its own I/O) ----
    check = await enrich.check_token(token)

    # ---- Moonshot path: accumulation on low-MC tokens, wider windows ----
    if in_moonshot and (hit.get("sol_amount") or 0) >= config.MOONSHOT_MIN_BUY_SOL:
        from . import moonshot
        await moonshot.evaluate(token, tok["chain_id"], tok["age_hours"],
                                check, wallet)

    # ---- Momentum path (original) ----
    if not in_momentum:
        return
    if (hit.get("sol_amount") or 0) < config.MIN_BUY_SOL:
        log.info("skip dust buy %.3f SOL on %s", hit.get("sol_amount") or 0, token[:8])
        return
    gated = bool(check["passed"])

    async with db.pool().acquire() as con:
        score, buyers, confluence = await _score(con, token)
        freshness = max(0.0, 1 - (tok["age_hours"] / config.FRESH_HOURS))
        score = round(score * (1 + 0.5 * freshness), 3)

        reason = (
            f"{buyers} wallet(s) in ({confluence} within 30m), "
            f"first seen {tok['age_hours']:.1f}h ago via {tok['source']}, "
            f"liq ${check['liquidity_usd'] or 0:,.0f}, "
            f"top10 {check['top10_pct'] or '?'}%"
        )
        if not gated:
            reason += f" | GATED OUT: {check['fail_reasons']}"

        sig_id = await con.fetchval(
            "INSERT INTO signals (chain_id, token_address, wallet, reason, score, gated) "
            "VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
            tok["chain_id"], token, wallet, reason, score, gated,
        )

    if not gated:
        log.info("filtered %s: %s", token[:8], check["fail_reasons"])
        return
    if score < config.MIN_SIGNAL_SCORE:
        log.info("below threshold %s score=%s", token[:8], score)
        return

    log.info("SIGNAL score=%s %s (%s)", score, token[:8], reason)
    await notify.send(
        title=f"🚨 Signal {score} — {buyers} wallet(s)",
        body=f"{reason}\nhttps://dexscreener.com/{tok['chain_id']}/{token}",
    )

    if config.PAPER_ENABLED and check.get("price_usd"):
        from . import paper
        await paper.open_trade(sig_id, token, wallet, check["price_usd"])

async def on_discovery(_row: dict) -> None:
    return
