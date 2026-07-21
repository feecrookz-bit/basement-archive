"""Dashboard sign-in — single-operator, right-sized.

Self-hosted software gets one password, not an identity provider. Auth is
env-driven and OFF when DASHBOARD_PASSWORD is unset (localhost / SSH-forward
users lose nothing). When enabled, /api/auth/login exchanges the password for
an HMAC-signed, expiring session token in an httpOnly cookie; every other
/api route 401s without it. Stdlib only — no new dependencies.
"""
import hashlib
import hmac
import os
import secrets
import time

COOKIE_NAME = "sentinel_session"
DEFAULT_MAX_AGE = 7 * 24 * 3600  # 7 days


def password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "")


def enabled() -> bool:
    return bool(password())


def _secret() -> bytes:
    s = os.getenv("SESSION_SECRET")
    if not s:
        # derive a boot-stable secret; set SESSION_SECRET to survive restarts
        s = os.environ.setdefault("_SENTINEL_BOOT_SECRET", secrets.token_hex(32))
    return s.encode()


def check_password(candidate: str) -> bool:
    if not enabled():
        return False
    return hmac.compare_digest(candidate.encode(), password().encode())


def sign(ts: int | None = None) -> str:
    ts = int(ts if ts is not None else time.time())
    payload = str(ts)
    mac = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def verify(token: str | None, max_age: int = DEFAULT_MAX_AGE) -> bool:
    if not token or "." not in token:
        return False
    payload, mac = token.rsplit(".", 1)
    expect = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expect):
        return False
    try:
        ts = int(payload)
    except ValueError:
        return False
    age = time.time() - ts
    return 0 <= age <= max_age
