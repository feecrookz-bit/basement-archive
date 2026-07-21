"""Helius webhook auto-management — makes the FREE-tier path hands-off.

WALLET_MODE=webhook (free Helius plan) needs an *enhanced* webhook in
Helius pointing at our /webhooks/helius route, carrying the tracked
addresses. Managing that by hand in the dashboard on every wallet change
is error-prone, so this module keeps it in sync via the Helius REST API:

  - on startup (webhook mode only): create the webhook if missing
  - on wallet add/remove: update its accountAddresses list

The public URL is taken from WEBHOOK_PUBLIC_URL, or auto-derived inside
GitHub Codespaces from CODESPACE_NAME (port 8000 must be set to Public
visibility in the Ports panel — Helius can't reach a private forward).
"""
import logging
import os

import aiohttp

from . import config, db

log = logging.getLogger("helius_webhooks")

API = "https://api.helius.xyz/v0/webhooks"


def public_webhook_url() -> str | None:
    explicit = (config.WEBHOOK_PUBLIC_URL or "").strip().rstrip("/")
    if explicit:
        return explicit if explicit.endswith("/webhooks/helius") \
            else f"{explicit}/webhooks/helius"
    name = os.getenv("CODESPACE_NAME")
    if name:
        domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN",
                           "app.github.dev")
        return f"https://{name}-8000.{domain}/webhooks/helius"
    return None


async def _tracked() -> list[str]:
    async with db.pool().acquire() as con:
        return [r["wallet"] for r in await con.fetch(
            "SELECT wallet FROM tracked_wallets")]


async def sync(reason: str = "") -> None:
    """Create/update our Helius enhanced webhook to match tracked_wallets.
    Silent no-op unless webhook mode with a key; never raises."""
    if config.WALLET_MODE != "webhook" or not config.HELIUS_API_KEY:
        return
    url = public_webhook_url()
    if not url:
        log.warning("webhook mode but no public URL: set WEBHOOK_PUBLIC_URL "
                    "(or run in Codespaces with port 8000 Public)")
        return
    wallets = await _tracked()
    if not wallets:
        log.info("no tracked wallets yet; webhook registration deferred")
        return
    try:
        async with aiohttp.ClientSession() as sess:
            params = {"api-key": config.HELIUS_API_KEY}
            async with sess.get(API, params=params, timeout=15) as r:
                if r.status != 200:
                    log.warning("helius webhook list -> HTTP %s", r.status)
                    return
                existing = await r.json(content_type=None) or []
            ours = next((w for w in existing
                         if w.get("webhookURL") == url), None)
            body = {
                "webhookURL": url,
                "transactionTypes": ["SWAP"],
                "accountAddresses": wallets,
                "webhookType": "enhanced",
            }
            if ours is None:
                async with sess.post(API, params=params, json=body,
                                     timeout=15) as r:
                    ok = r.status in (200, 201)
                    log.info("helius webhook created (%d wallet(s)) -> %s%s",
                             len(wallets), r.status,
                             f" [{reason}]" if reason else "")
                    if not ok:
                        log.warning("create failed: %s", await r.text())
            elif set(ours.get("accountAddresses") or []) != set(wallets):
                async with sess.put(f"{API}/{ours['webhookID']}",
                                    params=params, json=body, timeout=15) as r:
                    log.info("helius webhook updated (%d wallet(s)) -> %s%s",
                             len(wallets), r.status,
                             f" [{reason}]" if reason else "")
    except Exception as e:  # noqa: BLE001
        log.warning("helius webhook sync failed: %s", e)
