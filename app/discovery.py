"""
Discovery pipeline: surface newly listed / boosted / profiled meme coins from
DEX Screener.

Two modes (config.DISCOVERY_MODE):
  - "poll": GET the REST endpoints every few seconds. Officially supported,
            no key, 60 req/min limit -> we poll 4 endpoints, so keep >=4s.
  - "ws":   connect the streaming sockets with a spoofed browser Origin header.
            Lower latency but unofficial; the edge rejects bare clients.

Both feed the same upsert path, so signals don't care which you use.
"""
import asyncio
import json
import logging

import aiohttp

from . import config, db

log = logging.getLogger("discovery")

REST_BASE = "https://api.dexscreener.com"
WS_BASE = "wss://api.dexscreener.com"

# (path, source-tag). Order = priority; all are polled/streamed concurrently.
ENDPOINTS = [
    ("/token-profiles/latest/v1", "profile"),
    ("/token-boosts/latest/v1", "boost"),
    ("/token-boosts/top/v1", "boost_top"),
    ("/community-takeovers/latest/v1", "takeover"),
]

def _keep(chain_id: str) -> bool:
    if not config.DISCOVERY_CHAINS:
        return True
    return (chain_id or "").lower() in config.DISCOVERY_CHAINS

async def _upsert(items: list[dict], source: str) -> list[dict]:
    """Insert/refresh tokens. Return the rows that were brand new."""
    new_rows: list[dict] = []
    async with db.pool().acquire() as con:
        for it in items:
            chain = it.get("chainId")
            addr = it.get("tokenAddress")
            if not chain or not addr or not _keep(chain):
                continue
            row = await con.fetchrow(
                """
                INSERT INTO tokens
                    (chain_id, token_address, source, description, url, icon, boost_amount, last_seen)
                VALUES ($1,$2,$3,$4,$5,$6,$7, now())
                ON CONFLICT (chain_id, token_address) DO UPDATE
                    SET last_seen = now(),
                        boost_amount = COALESCE(EXCLUDED.boost_amount, tokens.boost_amount)
                RETURNING (xmax = 0) AS inserted
                """,
                chain, addr, source, it.get("description"), it.get("url"),
                it.get("icon"), it.get("totalAmount") or it.get("amount"),
            )
            if row and row["inserted"]:
                new_rows.append({"chain_id": chain, "token_address": addr, "source": source})
    if new_rows:
        log.info("discovery: %d new token(s) via %s", len(new_rows), source)
    return new_rows

# ---------------- REST polling ----------------
async def _poll_loop(on_new) -> None:
    async with aiohttp.ClientSession(headers=config.DEX_HEADERS) as sess:
        while True:
            for path, source in ENDPOINTS:
                try:
                    async with sess.get(REST_BASE + path, timeout=15) as r:
                        if r.status != 200:
                            log.warning("poll %s -> HTTP %s", path, r.status)
                            continue
                        payload = await r.json(content_type=None)
                except Exception as e:  # noqa: BLE001
                    log.warning("poll %s failed: %s", path, e)
                    continue
                # REST returns a bare list; WS wraps as {limit,data:[...]}.
                items = payload if isinstance(payload, list) else payload.get("data", [])
                for row in await _upsert(items, source):
                    await on_new(row)
            await asyncio.sleep(config.DISCOVERY_POLL_SECONDS)

# ---------------- WS streaming ----------------
async def _ws_endpoint(path: str, source: str, on_new) -> None:
    import websockets

    url = WS_BASE + path
    while True:
        try:
            async with websockets.connect(
                url, additional_headers=config.DEX_HEADERS, max_size=4_000_000
            ) as ws:
                log.info("ws connected: %s", path)
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        continue
                    items = payload.get("data", []) if isinstance(payload, dict) else []
                    for row in await _upsert(items, source):
                        await on_new(row)
        except Exception as e:  # noqa: BLE001
            log.warning("ws %s dropped (%s); reconnecting in 3s", path, e)
            await asyncio.sleep(3)

async def run(on_new) -> None:
    """on_new: async callback(dict) fired once per newly discovered token."""
    if config.DISCOVERY_MODE == "ws":
        await asyncio.gather(*(_ws_endpoint(p, s, on_new) for p, s in ENDPOINTS))
    else:
        await _poll_loop(on_new)
