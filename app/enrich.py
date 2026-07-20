"""
Token safety enrichment — the rug filter.

Pulls two independent views of a token and caches the verdict in token_checks:

1. DEX Screener REST `GET /latest/dex/tokens/{addr}` -> liquidity, 1h volume,
   FDV, price, pair age. (Official endpoint, 300 req/min tier.)
2. Helius RPC -> mint & freeze authority (must be revoked = null) and top-10
   holder concentration via getTokenLargestAccounts / getTokenSupply.

A token must pass ALL gates to produce an alertable signal. Failures are
recorded with reasons so you can audit what got filtered and tune thresholds.
"""
import logging
from datetime import datetime, timezone

import aiohttp

from . import config, db

log = logging.getLogger("enrich")

DEX_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{addr}"

async def _dex_pair(sess: aiohttp.ClientSession, addr: str) -> dict | None:
    """Best pair (highest liquidity) for the token, or None."""
    try:
        async with sess.get(DEX_TOKEN_URL.format(addr=addr), timeout=15) as r:
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.warning("dex pair fetch failed for %s: %s", addr[:8], e)
        return None
    pairs = (data or {}).get("pairs") or []
    if not pairs:
        return None
    return max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))

async def _rpc(sess: aiohttp.ClientSession, method: str, params: list):
    url = f"{config.HELIUS_RPC_URL}/?api-key={config.HELIUS_API_KEY}"
    async with sess.post(url, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params
    }, timeout=15) as r:
        body = await r.json(content_type=None)
        return body.get("result")

async def _mint_info(sess, addr: str) -> tuple[bool | None, bool | None]:
    """(mint_revoked, freeze_revoked); None means unknown."""
    if not config.HELIUS_API_KEY:
        return None, None
    try:
        res = await _rpc(sess, "getAccountInfo", [addr, {"encoding": "jsonParsed"}])
        info = (((res or {}).get("value") or {}).get("data") or {}) \
            .get("parsed", {}).get("info", {})
        if not info:
            return None, None
        return info.get("mintAuthority") is None, info.get("freezeAuthority") is None
    except Exception as e:  # noqa: BLE001
        log.warning("mint info failed for %s: %s", addr[:8], e)
        return None, None

async def _top10_pct(sess, addr: str) -> float | None:
    if not config.HELIUS_API_KEY:
        return None
    try:
        supply = await _rpc(sess, "getTokenSupply", [addr])
        total = float(((supply or {}).get("value") or {}).get("uiAmount") or 0)
        if total <= 0:
            return None
        largest = await _rpc(sess, "getTokenLargestAccounts", [addr])
        accounts = ((largest or {}).get("value") or [])[:11]
        # Largest account is almost always the LP pool; skip it, take next 10.
        holders = accounts[1:11] if len(accounts) > 1 else accounts
        held = sum(float(a.get("uiAmount") or 0) for a in holders)
        return round(100 * held / total, 2)
    except Exception as e:  # noqa: BLE001
        log.warning("holder check failed for %s: %s", addr[:8], e)
        return None

async def check_token(addr: str, force: bool = False) -> dict:
    """Run all gates, persist, return the row as dict (with passed/fail_reasons)."""
    async with db.pool().acquire() as con:
        if not force:
            cached = await con.fetchrow(
                "SELECT * FROM token_checks WHERE token_address=$1 "
                "AND checked_at > now() - interval '10 minutes'", addr)
            if cached:
                return dict(cached)

    async with aiohttp.ClientSession(headers=config.DEX_HEADERS) as sess:
        pair = await _dex_pair(sess, addr)
        mint_revoked, freeze_revoked = await _mint_info(sess, addr)
        top10 = await _top10_pct(sess, addr)

    liq = vol1h = fdv = price = None
    pair_addr = pair_created = None
    if pair:
        liq = float((pair.get("liquidity") or {}).get("usd") or 0)
        vol1h = float((pair.get("volume") or {}).get("h1") or 0)
        fdv = float(pair.get("fdv") or 0)
        price = float(pair.get("priceUsd") or 0) or None
        pair_addr = pair.get("pairAddress")
        if pair.get("pairCreatedAt"):
            pair_created = datetime.fromtimestamp(
                pair["pairCreatedAt"] / 1000, tz=timezone.utc)

    fails: list[str] = []
    if pair is None:
        fails.append("no tradable pair found")
    else:
        if (liq or 0) < config.MIN_LIQUIDITY_USD:
            fails.append(f"liquidity ${liq:,.0f} < ${config.MIN_LIQUIDITY_USD:,.0f}")
        if (vol1h or 0) < config.MIN_VOLUME_H1_USD:
            fails.append(f"1h volume ${vol1h:,.0f} < ${config.MIN_VOLUME_H1_USD:,.0f}")
        if fdv and fdv > config.MAX_FDV_USD:
            fails.append(f"FDV ${fdv:,.0f} > ${config.MAX_FDV_USD:,.0f} (late)")
    if config.REQUIRE_MINT_REVOKED and mint_revoked is False:
        fails.append("mint authority NOT revoked")
    if freeze_revoked is False:
        fails.append("freeze authority NOT revoked (honeypot risk)")
    if top10 is not None and top10 > config.MAX_TOP10_PCT:
        fails.append(f"top-10 holders {top10}% > {config.MAX_TOP10_PCT}%")

    row = {
        "token_address": addr, "liquidity_usd": liq, "volume_h1_usd": vol1h,
        "fdv_usd": fdv, "price_usd": price, "pair_address": pair_addr,
        "pair_created_at": pair_created, "mint_revoked": mint_revoked,
        "freeze_revoked": freeze_revoked, "top10_pct": top10,
        "passed": not fails, "fail_reasons": "; ".join(fails) or None,
    }
    async with db.pool().acquire() as con:
        await con.execute(
            """
            INSERT INTO token_checks (token_address, liquidity_usd, volume_h1_usd,
                fdv_usd, price_usd, pair_address, pair_created_at, mint_revoked,
                freeze_revoked, top10_pct, passed, fail_reasons, checked_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
            ON CONFLICT (token_address) DO UPDATE SET
                liquidity_usd=$2, volume_h1_usd=$3, fdv_usd=$4, price_usd=$5,
                pair_address=$6, pair_created_at=$7, mint_revoked=$8,
                freeze_revoked=$9, top10_pct=$10, passed=$11, fail_reasons=$12,
                checked_at=now()
            """,
            *[row[k] for k in ("token_address", "liquidity_usd", "volume_h1_usd",
                               "fdv_usd", "price_usd", "pair_address",
                               "pair_created_at", "mint_revoked", "freeze_revoked",
                               "top10_pct", "passed", "fail_reasons")],
        )
    return row

async def current_price(addr: str) -> float | None:
    """Lightweight price fetch for the paper-trade monitor."""
    async with aiohttp.ClientSession(headers=config.DEX_HEADERS) as sess:
        pair = await _dex_pair(sess, addr)
    if not pair:
        return None
    try:
        return float(pair.get("priceUsd") or 0) or None
    except (TypeError, ValueError):
        return None
