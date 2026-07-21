"""NEWS — Binance announcement monitoring for the pairs Sentinel trades.

Data, never a signal: announcements land on the bus (→ activity feed and
dashboard) and push a notification only when they touch a pair we hold or
watch. Delistings are the one that matters — holding through a delisting
notice is how a day trade becomes a donation.

The endpoint is Binance's public CMS (unofficial, 403-prone without browser
headers) — every failure is swallowed; news going dark must never affect
trading.
"""
import logging

log = logging.getLogger("news")

CMS_URL = ("https://www.binance.com/bapi/composite/v1/public/cms/article/"
           "catalog/list/query?catalogId=48&pageNo=1&pageSize=20")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/127.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def classify(title: str) -> str:
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


def mentioned_bases(title: str, bases: set[str]) -> list[str]:
    """Which of our base assets a title mentions (word-ish match, upper)."""
    up = f" {(title or '').upper()} "
    return sorted(b for b in bases
                  if f" {b} " in up or f"({b})" in up.replace(" ", ""))


async def fetch_articles(session) -> list[dict]:
    """Best-effort fetch; [] on any failure."""
    try:
        async with session.get(CMS_URL, headers=HEADERS, timeout=20) as r:
            if r.status != 200:
                log.debug("announcements -> HTTP %s (ignoring)", r.status)
                return []
            body = await r.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        log.debug("announcements fetch failed: %s", e)
        return []
    articles = (((body or {}).get("data") or {}).get("articles")
                or (body or {}).get("data") or [])
    return articles if isinstance(articles, list) else []


async def check(session, bus, bases: set[str], seen: set[str],
                notify_send) -> int:
    """One poll cycle. Publishes new articles touching our pairs; notifies on
    delistings (exit-now) and launchpool/airdrop windows. Returns # published."""
    published = 0
    for a in await fetch_articles(session):
        title = a.get("title") or ""
        code = str(a.get("code") or title[:60])
        if code in seen:
            continue
        seen.add(code)
        cat = classify(title)
        hits = mentioned_bases(title, bases)
        if not hits and cat not in ("launchpool", "hodler_airdrop"):
            continue  # not our pairs, not a standing window — skip quietly
        url = (f"https://www.binance.com/en/support/announcement/{a.get('code')}"
               if a.get("code") else None)
        await bus.publish("news", "news.announcement",
                          {"title": title, "category": cat,
                           "pairs": hits, "url": url})
        published += 1
        if cat == "delisting" and hits:
            await notify_send(
                title=f"🚨 DELISTING touches {', '.join(hits)}",
                body=f"{title}\nExit-now framing: delisted pairs bleed into "
                     f"the removal date.\n{url or ''}")
        elif cat in ("launchpool", "hodler_airdrop"):
            await notify_send(
                title=f"🔶 Binance {cat.replace('_', ' ')}",
                body=f"{title}\n{url or ''}")
        elif hits:
            await notify_send(
                title=f"📰 Binance news — {', '.join(hits)}",
                body=f"[{cat}] {title}\n{url or ''}")
    # cap the dedup set so a long-running process doesn't grow unbounded
    if len(seen) > 500:
        for extra in list(seen)[: len(seen) - 400]:
            seen.discard(extra)
    return published
