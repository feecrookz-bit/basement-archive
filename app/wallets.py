"""
Wallet pipeline: watch tracked Solana wallets and record token buys/sells.

Primary: Helius `transactionSubscribe` on the Atlas enhanced socket (outbound,
real-time, needs a paid Helius plan). Fallback: Helius enhanced *webhooks*
POSTed to /webhooks/helius (works on the free tier) -> handled by parse_webhook().

Buy/sell direction is derived from pre/post token balances: if the tracked
wallet's balance of a mint went UP, that's a buy of that mint; DOWN = sell.
This is source-agnostic (works for any DEX/aggregator) and avoids brittle
program-specific decoding.
"""
import asyncio
import json
import logging

from . import config, db

log = logging.getLogger("wallets")

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
QUOTE_MINTS = {WSOL, USDC}  # ignore these as the "token" side of a swap

async def tracked_wallets() -> list[str]:
    async with db.pool().acquire() as con:
        rows = await con.fetch("SELECT wallet FROM tracked_wallets")
    return [r["wallet"] for r in rows]

async def record_hit(wallet, token, side, tx_sig, on_hit, sol_amount=None) -> None:
    async with db.pool().acquire() as con:
        row = await con.fetchrow(
            """
            INSERT INTO wallet_hits (wallet, token_address, side, tx_sig, sol_amount)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (tx_sig, token_address, side) DO NOTHING
            RETURNING id
            """,
            wallet, token, side, tx_sig, sol_amount,
        )
    if row:
        log.info("wallet %s %s %s (%.2f SOL)", wallet[:6], side, token[:8], sol_amount or 0)
        await on_hit({"wallet": wallet, "token_address": token, "side": side,
                      "tx_sig": tx_sig, "sol_amount": sol_amount})

def _sol_notional(tx: dict, meta: dict, owner: str) -> float | None:
    """Approximate SOL size of the swap for `owner`: native lamport delta plus
    WSOL token delta. Sign-agnostic — we only care about magnitude."""
    total = 0.0
    try:
        keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        for i, k in enumerate(keys):
            pk = k.get("pubkey") if isinstance(k, dict) else k
            if pk == owner:
                pre = (meta.get("preBalances") or [])
                post = (meta.get("postBalances") or [])
                if i < len(pre) and i < len(post):
                    total += abs(post[i] - pre[i]) / 1e9
                break
    except Exception:  # noqa: BLE001
        pass
    # WSOL leg
    pre_w = post_w = 0.0
    for b in meta.get("preTokenBalances", []) or []:
        if b.get("owner") == owner and b.get("mint") == WSOL:
            pre_w += float(b["uiTokenAmount"].get("uiAmount") or 0)
    for b in meta.get("postTokenBalances", []) or []:
        if b.get("owner") == owner and b.get("mint") == WSOL:
            post_w += float(b["uiTokenAmount"].get("uiAmount") or 0)
    total += abs(post_w - pre_w)
    return round(total, 4) if total > 0 else None

def _deltas_from_meta(meta: dict, owners: set[str]) -> dict[tuple[str, str], float]:
    """{(owner, mint): ui_amount_delta} for the owners we care about."""
    pre, post = {}, {}
    for b in meta.get("preTokenBalances", []) or []:
        if b.get("owner") in owners:
            pre[(b["owner"], b["mint"])] = float(b["uiTokenAmount"].get("uiAmount") or 0)
    for b in meta.get("postTokenBalances", []) or []:
        if b.get("owner") in owners:
            post[(b["owner"], b["mint"])] = float(b["uiTokenAmount"].get("uiAmount") or 0)
    deltas = {}
    for key in set(pre) | set(post):
        d = post.get(key, 0) - pre.get(key, 0)
        if abs(d) > 1e-9:
            deltas[key] = d
    return deltas

async def _handle_tx(tx: dict, sig: str, owners: set[str], on_hit) -> None:
    meta = tx.get("meta") or {}
    for (owner, mint), delta in _deltas_from_meta(meta, owners).items():
        if mint in QUOTE_MINTS:  # SOL/USDC leg, not the meme token
            continue
        side = "buy" if delta > 0 else "sell"
        await record_hit(owner, mint, side, sig, on_hit,
                         sol_amount=_sol_notional(tx, meta, owner))

# ---------------- Atlas WebSocket ----------------

async def _ws_loop(on_hit) -> None:
    import websockets

    url = f"{config.HELIUS_WS_URL}/?api-key={config.HELIUS_API_KEY}"
    while True:
        wallets = set(await tracked_wallets())
        if not wallets:
            await asyncio.sleep(10)
            continue
        try:
            async with websockets.connect(url, max_size=8_000_000) as ws:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "transactionSubscribe",
                    "params": [
                        {"failed": False, "accountInclude": list(wallets)},
                        {"commitment": "confirmed", "encoding": "jsonParsed",
                         "transactionDetails": "full", "maxSupportedTransactionVersion": 0},
                    ],
                }))
                log.info("helius ws subscribed to %d wallet(s)", len(wallets))
                async for raw in ws:
                    msg = json.loads(raw)
                    res = (msg.get("params") or {}).get("result")
                    if not res:
                        continue
                    tx = res.get("transaction", res)
                    sig = (tx.get("transaction", {}).get("signatures") or [None])[0] \
                        or res.get("signature")
                    await _handle_tx(tx, sig, wallets, on_hit)
                    # cheap re-subscribe check if wallet set changed
                    if set(await tracked_wallets()) != wallets:
                        break
        except Exception as e:  # noqa: BLE001
            log.warning("helius ws dropped (%s); reconnecting in 3s", e)
            await asyncio.sleep(3)

async def parse_webhook(payload: list | dict, on_hit) -> None:
    """Handle a Helius enhanced-webhook POST body (fallback path)."""
    owners = set(await tracked_wallets())
    events = payload if isinstance(payload, list) else [payload]
    for ev in events:
        sig = ev.get("signature")
        # Enhanced payloads carry parsed tokenTransfers; use them directly.
        for t in ev.get("tokenTransfers", []) or []:
            mint = t.get("mint")
            if not mint or mint in QUOTE_MINTS:
                continue
            sol_amt = None
            for nt in ev.get("nativeTransfers", []) or []:
                if nt.get("fromUserAccount") in owners or nt.get("toUserAccount") in owners:
                    sol_amt = round((sol_amt or 0) + abs(nt.get("amount", 0)) / 1e9, 4)

            if t.get("toUserAccount") in owners:
                await record_hit(t["toUserAccount"], mint, "buy", sig, on_hit, sol_amount=sol_amt)
            elif t.get("fromUserAccount") in owners:
                await record_hit(t["fromUserAccount"], mint, "sell", sig, on_hit, sol_amount=sol_amt)

async def run(on_hit) -> None:
    if config.WALLET_MODE == "ws":
        if not config.HELIUS_API_KEY:
            log.error("WALLET_MODE=ws but HELIUS_API_KEY is empty; wallet tracking disabled")
            return
        await _ws_loop(on_hit)
    elif config.WALLET_MODE == "webhook":
        log.info("wallet mode = webhook; waiting for POSTs at /webhooks/helius")
        while True:  # nothing to poll; the route drives ingestion
            await asyncio.sleep(3600)
    else:
        log.info("wallet tracking disabled (WALLET_MODE=%s)", config.WALLET_MODE)
