"""Optional outbound alerts. No-ops if the relevant env vars are unset."""
import logging

import aiohttp

from . import config

log = logging.getLogger("notify")

async def send(title: str, body: str) -> None:
    text = f"**{title}**\n{body}"
    async with aiohttp.ClientSession() as sess:
        if config.DISCORD_WEBHOOK_URL:
            try:
                await sess.post(config.DISCORD_WEBHOOK_URL, json={"content": text}, timeout=10)
            except Exception as e:  # noqa: BLE001
                log.warning("discord alert failed: %s", e)
        if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            try:
                await sess.post(url, json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": f"{title}\n{body}",
                    "disable_web_page_preview": False,
                }, timeout=10)
            except Exception as e:  # noqa: BLE001
                log.warning("telegram alert failed: %s", e)
