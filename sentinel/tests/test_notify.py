"""Notify must be a silent no-op when unconfigured and must never raise."""
import asyncio

from sentinel import notify


def test_unconfigured_by_default(monkeypatch):
    monkeypatch.setattr(notify, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(notify, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notify, "TELEGRAM_CHAT_ID", "")
    assert notify.configured() is False
    # send() is a no-op — must return without any network attempt or error
    asyncio.run(notify.send("title", "body"))


def test_configured_variants(monkeypatch):
    monkeypatch.setattr(notify, "DISCORD_WEBHOOK_URL", "https://discord/hook")
    monkeypatch.setattr(notify, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notify, "TELEGRAM_CHAT_ID", "")
    assert notify.configured() is True

    monkeypatch.setattr(notify, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(notify, "TELEGRAM_BOT_TOKEN", "tok")
    assert notify.configured() is False  # telegram needs BOTH token and chat id
    monkeypatch.setattr(notify, "TELEGRAM_CHAT_ID", "123")
    assert notify.configured() is True


def test_send_never_raises_on_network_failure(monkeypatch):
    # point at an unroutable webhook — send() must swallow the failure
    monkeypatch.setattr(notify, "DISCORD_WEBHOOK_URL",
                        "http://127.0.0.1:1/does-not-exist")
    monkeypatch.setattr(notify, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notify, "TELEGRAM_CHAT_ID", "")
    asyncio.run(notify.send("title", "body"))  # no exception = pass
