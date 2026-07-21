"""Outbound notifications — Discord webhook + Telegram. Env-driven, silent
no-op when unset, never raises (an alert failure must never touch trading).
Mirrors the tracker's proven app/notify.py."""
import logging
import os

import aiohttp

log = logging.getLogger("notify")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def configured() -> bool:
    return bool(DISCORD_WEBHOOK_URL or (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID))


async def send(title: str, body: str) -> None:
    if not configured():
        return
    text = f"**{title}**\n{body}"
    try:
        async with aiohttp.ClientSession() as sess:
            if DISCORD_WEBHOOK_URL:
                try:
                    await sess.post(DISCORD_WEBHOOK_URL,
                                    json={"content": text}, timeout=10)
                except Exception as e:  # noqa: BLE001
                    log.warning("discord alert failed: %s", e)
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                url = (f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
                       f"/sendMessage")
                try:
                    await sess.post(url, json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": f"{title}\n{body}",
                        "disable_web_page_preview": True,
                    }, timeout=10)
                except Exception as e:  # noqa: BLE001
                    log.warning("telegram alert failed: %s", e)
    except Exception as e:  # noqa: BLE001
        log.warning("notify failed entirely: %s", e)
