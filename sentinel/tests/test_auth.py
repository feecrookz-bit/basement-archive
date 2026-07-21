"""Auth token matrix — sign/verify round-trip, expiry, tamper, disabled mode."""
import time

import pytest

from sentinel import auth


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-for-auth-tests")
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    yield


def test_disabled_when_password_unset():
    assert auth.enabled() is False
    # with auth off, no candidate password ever authenticates
    assert auth.check_password("") is False
    assert auth.check_password("anything") is False


def test_enabled_and_check_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "hunter2")
    assert auth.enabled() is True
    assert auth.check_password("hunter2") is True
    assert auth.check_password("Hunter2") is False
    assert auth.check_password("") is False


def test_sign_verify_round_trip():
    token = auth.sign()
    assert auth.verify(token) is True


def test_verify_rejects_garbage():
    assert auth.verify(None) is False
    assert auth.verify("") is False
    assert auth.verify("no-dot-here") is False
    assert auth.verify("notanumber.deadbeef") is False


def test_verify_rejects_tampered_mac():
    token = auth.sign()
    payload, mac = token.rsplit(".", 1)
    flipped = ("0" if mac[0] != "0" else "1") + mac[1:]
    assert auth.verify(f"{payload}.{flipped}") is False


def test_verify_rejects_tampered_payload():
    token = auth.sign()
    payload, mac = token.rsplit(".", 1)
    assert auth.verify(f"{int(payload) + 1}.{mac}") is False


def test_verify_rejects_expired():
    old = auth.sign(int(time.time()) - auth.DEFAULT_MAX_AGE - 10)
    assert auth.verify(old) is False
    # custom, tighter max_age
    recent = auth.sign(int(time.time()) - 120)
    assert auth.verify(recent, max_age=60) is False
    assert auth.verify(recent, max_age=3600) is True


def test_verify_rejects_future_timestamp():
    ahead = auth.sign(int(time.time()) + 3600)
    assert auth.verify(ahead) is False


def test_secret_change_invalidates(monkeypatch):
    token = auth.sign()
    monkeypatch.setenv("SESSION_SECRET", "rotated-secret")
    assert auth.verify(token) is False
