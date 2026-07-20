"""
Pump.fun graduation watcher — Method 2 (the bonding-curve window).

Feed: PumpPortal's free public WebSocket (no key needed).
  - subscribeNewToken  -> seed launches into `tokens` (source='pumpfun') so
    wallet buys on brand-new launches enter the signal pipeline.
  - subscribeMigration -> a token graduated (curve complete, liquidity moved
    to Raydium/PumpSwap). Recorded in `graduations`.

The tradeable pattern per the research is NOT the graduation itself — it's
the post-graduation dump->reclaim: early curve buyers dump into the new
pool (typically -30..60% in the first hour), and if price then reclaims the
graduation level, the weak hands are out and the level is defined. That
reclaim emits a `kind='graduation'` signal (still passed through the
standard safety gates) and opens a paper trade, so the ledger measures
whether the pattern earns anything. Tokens that never reclaim were nothing,
and cost nothing.
"""
import asyncio
import json
import logging

from . import config, db, enrich, notify

log = logging.getLogger("pumpfun")

async def _seed_token(mint: str, name: str | None, symbol: str | None) -> None:
    async with db.pool().acquire() as con:
        await con.execute(
            """
            INSERT INTO tokens (chain_id, token_address, source, description, last_seen)
            VALUES ('solana', $1, 'pumpfun', $2, now())
            ON CONFLICT (chain_id, token_address) DO UPDATE SET last_seen = now()
            """,
            mint, " ".join(x for x in (name, f"({symbol})" if symbol else None) if x) or None,
        )

async def _record_graduation(mint: str) -> None:
    async with db.pool().acquire() as con:
        inserted = await con.fetchrow(
            """
            INSERT INTO graduations (token_address) VALUES ($1)
            ON CONFLICT (token_address) DO NOTHING RETURNING token_address
            """,
            mint,
        )
        if not inserted:
            return
        # Alert only when the token was already on our radar — every pump.fun
        # migration would otherwise spam the channel.
        interesting = await con.fetchval(
            """
            SELECT 1 FROM wallet_hits WHERE token_address=$1
            UNION SELECT 1 FROM signals WHERE token_address=$1 LIMIT 1
            """, mint)
    log.info("graduated: %s", mint[:8])
    if interesting:
        await notify.send(
            title="🎓 Graduation — tracked token left the curve",
            body=(f"{mint[:10]}… migrated to Raydium/PumpSwap. Watching for the "
                  f"dump→reclaim entry.\nhttps://dexscreener.com/solana/{mint}"),
        )

async def _ws_loop() -> None:
    import websockets

    while True:
        try:
            async with websockets.connect(config.PUMPPORTAL_WS_URL, max_size=4_000_000) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                log.info("pumpportal ws connected (launches + migrations)")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        continue
                    mint = msg.get("mint")
                    if not mint:
                        continue
                    tx_type = (msg.get("txType") or "").lower()
                    if tx_type == "create":
                        await _seed_token(mint, msg.get("name"), msg.get("symbol"))
                    elif tx_type == "migrate":
                        await _record_graduation(mint)
        except Exception as e:  # noqa: BLE001
            log.warning("pumpportal ws dropped (%s); reconnecting in 3s", e)
            await asyncio.sleep(3)

async def _fire_reclaim(con, g, price: float) -> None:
    dump_pct = 100 * (g["grad_price"] - g["low_price"]) / g["grad_price"]
    await con.execute(
        "UPDATE graduations SET reclaimed=true, reclaimed_at=now() WHERE token_address=$1",
        g["token_address"])
    check = await enrich.check_token(g["token_address"])
    gated = bool(check["passed"])
    score = round(1 + dump_pct / 100, 3)  # deeper flush survived = cleaner signal
    reason = (
        f"GRADUATION RECLAIM: dumped {dump_pct:.0f}% post-migration, reclaimed "
        f"{g['grad_price']:.10f}; liq ${check['liquidity_usd'] or 0:,.0f}, "
        f"top10 {check['top10_pct'] or '?'}%"
    )
    if not gated:
        reason += f" | GATED OUT: {check['fail_reasons']}"
    sig_id = await con.fetchval(
        "INSERT INTO signals (chain_id, token_address, wallet, reason, score, gated, kind) "
        "VALUES ('solana', $1, 'pumpfun:migration', $2, $3, $4, 'graduation') RETURNING id",
        g["token_address"], reason, score, gated,
    )
    if not gated:
        log.info("graduation reclaim filtered %s: %s", g["token_address"][:8],
                 check["fail_reasons"])
        return
    log.info("GRADUATION RECLAIM %s (%.0f%% dump)", g["token_address"][:8], dump_pct)
    await notify.send(
        title=f"🎓 Reclaim {score} — dump survived",
        body=f"{reason}\nhttps://dexscreener.com/solana/{g['token_address']}",
    )
    if config.PAPER_ENABLED and check.get("price_usd"):
        from . import paper
        await paper.open_trade(sig_id, g["token_address"], "pumpfun:migration",
                               check["price_usd"], kind="graduation")

async def reclaim_monitor() -> None:
    """Track post-graduation price path: record the low, fire on reclaim."""
    if not config.PUMPFUN_ENABLED:
        return
    while True:
        try:
            async with db.pool().acquire() as con:
                grads = await con.fetch(
                    f"""
                    SELECT * FROM graduations
                    WHERE NOT reclaimed
                      AND migrated_at > now() - interval '{config.GRAD_RECLAIM_WINDOW_HOURS} hours'
                    ORDER BY migrated_at DESC
                    LIMIT {config.GRAD_MONITOR_MAX}
                    """)
            for g in grads:
                price = await enrich.current_price(g["token_address"])
                if price is None:
                    continue  # pair not indexed yet (or already dead — window expires it)
                async with db.pool().acquire() as con:
                    if g["grad_price"] is None:
                        await con.execute(
                            "UPDATE graduations SET grad_price=$1, low_price=$1 "
                            "WHERE token_address=$2", price, g["token_address"])
                        continue
                    if price < (g["low_price"] or price):
                        await con.execute(
                            "UPDATE graduations SET low_price=$1 WHERE token_address=$2",
                            price, g["token_address"])
                        continue
                    dump_pct = 100 * (g["grad_price"] - (g["low_price"] or g["grad_price"])) \
                        / g["grad_price"]
                    if dump_pct >= config.GRAD_MIN_DUMP_PCT and price >= g["grad_price"]:
                        await _fire_reclaim(con, g, price)
        except Exception as e:  # noqa: BLE001
            log.warning("reclaim monitor error: %s", e)
        await asyncio.sleep(config.PAPER_CHECK_SECONDS)

async def run() -> None:
    if not config.PUMPFUN_ENABLED:
        log.info("pumpfun watcher disabled")
        return
    await _ws_loop()
