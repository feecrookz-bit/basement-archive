"""
Binance touchpoint watcher — exit-liquidity flags, not price prediction.

A low-cap's best historical liquidity event is a Binance touchpoint:
inclusion in Binance Alpha (early-token showcase, public no-auth API) or a
listing announcement. This worker polls both and alerts when a token we
actually care about — discovered, signalled, or held in the paper ledger —
shows up. The alert marks a *window to secure profits*, per the research:
the pump is historically into the announcement, distribution after.

Announcements are also classified by category. Two categories alert even
without a tracked-token match, because they are rare and high-signal on
their own (Method 5, the boring compounder): LAUNCHPOOL events (stake
BNB/stables, farm the new token, historical playbook = sell the emission
on listing day) and HODLER AIRDROPS. Listings/delistings only alert when
they touch our working set.

Both endpoints are bapi (browser-gated like DEX Screener's edge), so we
reuse DEX_HEADERS. The announcements endpoint is unofficial and 403-prone:
failures are logged and skipped, never fatal.
"""
import asyncio
import logging
import re

import aiohttp

from . import config, db, notify

log = logging.getLogger("binance")

TICKER_RE = re.compile(r"\(([A-Z0-9]{2,10})\)")


def classify_announcement(title: str) -> str:
    """Category slug for an announcement title."""
    t = (title or "").lower()
    if "launchpool" in t:
        return "launchpool"
    if "hodler airdrop" in t or "hodler airdrops" in t:
        return "hodler_airdrop"
    if "will delist" in t or "delisting" in t:
        return "delisting"
    if "will list" in t or "will add" in t or "listing" in t:
        return "listing"
    return "other"


def extract_tickers(title: str) -> list[str]:
    """Tickers in parentheses, e.g. 'Will List Dogwifhat (WIF)' -> ['WIF']."""
    return TICKER_RE.findall(title or "")

async def _working_set(con) -> dict[str, str]:
    """{lowercased token_address: why we care} for matching."""
    out: dict[str, str] = {}
    for q, label in (
        ("SELECT token_address FROM tokens", "discovered"),
        ("SELECT token_address FROM signals WHERE gated", "signalled"),
        ("SELECT token_address FROM paper_trades WHERE status='open'", "open paper trade"),
    ):
        for r in await con.fetch(q):
            out[r["token_address"].lower()] = label  # later = stronger reason wins
    return out

async def _record_event(con, token: str, symbol: str | None, event_type: str,
                        title: str | None, url: str | None) -> bool:
    """Insert once; True when this is a brand-new event."""
    row = await con.fetchrow(
        """
        INSERT INTO binance_events (token_address, symbol, event_type, title, url)
        VALUES ($1,$2,$3,$4,$5)
        ON CONFLICT (token_address, event_type, title) DO NOTHING
        RETURNING id
        """,
        token, symbol, event_type, title, url,
    )
    return row is not None

async def _check_alpha(sess: aiohttp.ClientSession) -> None:
    async with sess.get(config.BINANCE_ALPHA_URL, timeout=20) as r:
        if r.status != 200:
            log.warning("alpha list -> HTTP %s", r.status)
            return
        body = await r.json(content_type=None)
    tokens = (body or {}).get("data") or []
    # {contract address (lowercase): symbol}
    listed = {}
    for t in tokens:
        addr = (t.get("contractAddress") or t.get("tokenAddress") or "").strip()
        if addr:
            listed[addr.lower()] = t.get("symbol") or t.get("name")
    if not listed:
        return
    async with db.pool().acquire() as con:
        ours = await _working_set(con)
        for addr in set(listed) & set(ours):
            new = await _record_event(
                con, addr, listed[addr], "alpha",
                f"Binance Alpha inclusion: {listed[addr]}", None)
            if new:
                log.info("BINANCE ALPHA hit: %s (%s)", listed[addr], ours[addr])
                await notify.send(
                    title=f"🔶 Binance Alpha — {listed[addr]}",
                    body=(f"{addr} ({ours[addr]}) is now on Binance Alpha.\n"
                          f"Historically the strongest liquidity/attention window a "
                          f"low-cap gets — consider securing profits.\n"
                          f"https://dexscreener.com/solana/{addr}"),
                )

async def _check_announcements(sess: aiohttp.ClientSession) -> None:
    """Best-effort: unofficial endpoint, 403s without browser context are normal."""
    try:
        async with sess.get(config.BINANCE_CMS_URL, timeout=20) as r:
            if r.status != 200:
                log.debug("announcements -> HTTP %s (unofficial endpoint; ignoring)", r.status)
                return
            body = await r.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.debug("announcements fetch failed: %s", e)
        return
    articles = (((body or {}).get("data") or {}).get("articles")
                or (body or {}).get("data") or [])
    if not isinstance(articles, list) or not articles:
        return
    async with db.pool().acquire() as con:
        # Match by symbol from gated signals' tokens: cheap heuristic — titles
        # carry tickers in parentheses, e.g. "Binance Will List Dogwifhat (WIF)".
        rows = await con.fetch(
            """
            SELECT DISTINCT s.token_address, b.symbol
            FROM signals s
            LEFT JOIN binance_events b ON b.token_address = s.token_address
            WHERE s.gated
            """)
        known = {(r["symbol"] or "").upper(): r["token_address"] for r in rows if r["symbol"]}
        for a in articles:
            title = a.get("title") or ""
            code = a.get("code")
            url = f"https://www.binance.com/en/support/announcement/{code}" if code else None
            cat = classify_announcement(title)
            tickers = extract_tickers(title)

            # Method 5 events alert unconditionally — rare, self-signal
            if cat in ("launchpool", "hodler_airdrop"):
                key = f"binance:{code or title[:40]}"
                if await _record_event(con, key, ",".join(tickers) or None,
                                       cat, title, url):
                    log.info("BINANCE %s: %s", cat.upper(), title)
                    what = ("Launchpool window — stake BNB/FDUSD, farm, and note "
                            "the historical playbook: sell the emission into "
                            "listing-day hype." if cat == "launchpool" else
                            "HODLer Airdrop — passive BNB holders get the drop; "
                            "same sell-the-emission logic applies.")
                    await notify.send(
                        title=f"🔶 Binance {cat.replace('_', ' ')} — "
                              f"{','.join(tickers) or 'new event'}",
                        body=f"{title}\n{what}\n{url or ''}",
                    )
                continue

            # Listings/delistings: only when they touch our working set
            for sym, addr in known.items():
                if sym and f"({sym})" in title.upper():
                    if await _record_event(con, addr, sym, cat, title, url):
                        log.info("BINANCE %s hit: %s", cat.upper(), title)
                        framing = ("Delisting — liquidity will drain; exit "
                                   "window is NOW, not after."
                                   if cat == "delisting" else
                                   "Listing pumps are historically "
                                   "sell-the-news — distribution follows "
                                   "the spike.")
                        await notify.send(
                            title=f"🔶 Binance {cat} — {sym}",
                            body=f"{title}\n{framing}\n{url or ''}",
                        )

async def run() -> None:
    if not config.BINANCE_ENABLED:
        log.info("binance watcher disabled")
        return
    while True:
        try:
            async with aiohttp.ClientSession(headers=config.DEX_HEADERS) as sess:
                await _check_alpha(sess)
                await _check_announcements(sess)
        except Exception as e:  # noqa: BLE001
            log.warning("binance watcher error: %s", e)
        await asyncio.sleep(config.BINANCE_POLL_SECONDS)
