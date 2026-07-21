"""Session and level tracking — the ICT map: where does liquidity rest?

Sessions (UTC windows from config) give session highs/lows and swept flags;
1h candles give previous-day/week extremes (PDH/PDL/PWH/PWL) with hit
flags. All pure functions of (candles, now)."""
from datetime import datetime, time, timedelta, timezone

DEFAULT_SESSIONS = {
    "asia": {"start": "00:00", "end": "08:00"},
    "london": {"start": "07:00", "end": "12:00"},
    "newyork": {"start": "12:30", "end": "20:00"},
}


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _candle_dt(c: dict) -> datetime:
    return datetime.fromtimestamp(c["ts"] / 1000, tz=timezone.utc)


def session_state(candles_15m: list[dict], now: datetime,
                  sessions: dict | None = None) -> dict:
    """Per-session view for the current UTC day:
    {name: {high, low, status: waiting|open|closed, high_swept, low_swept}}
    Swept = a later candle (after the session closed) traded through the
    session extreme."""
    sessions = sessions or DEFAULT_SESSIONS
    day = now.date()
    out: dict = {"current": None}
    for name, win in sessions.items():
        start = datetime.combine(day, _t(win["start"]), tzinfo=timezone.utc)
        end = datetime.combine(day, _t(win["end"]), tzinfo=timezone.utc)
        in_session = [c for c in candles_15m if start <= _candle_dt(c) < end
                      and _candle_dt(c) <= now]
        if now < start:
            out[name] = {"status": "waiting", "high": None, "low": None,
                         "high_swept": False, "low_swept": False}
            continue
        status = "open" if now < end else "closed"
        if status == "open":
            out["current"] = name
        if not in_session:
            out[name] = {"status": status, "high": None, "low": None,
                         "high_swept": False, "low_swept": False}
            continue
        hi = max(c["high"] for c in in_session)
        lo = min(c["low"] for c in in_session)
        after = [c for c in candles_15m if _candle_dt(c) >= end
                 and _candle_dt(c) <= now]
        out[name] = {
            "status": status,
            "high": hi, "low": lo,
            "high_swept": any(c["high"] > hi for c in after),
            "low_swept": any(c["low"] < lo for c in after),
        }
    return out


def day_levels(candles_1h: list[dict], now: datetime) -> dict:
    """PDH/PDL (previous UTC day) and PWH/PWL (previous ISO week) with hit
    flags from price action since those periods closed."""
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())      # this Monday
    prev_week_start = week_start - timedelta(days=7)

    def extremes(frm, to):
        rows = [c for c in candles_1h if frm <= _candle_dt(c).date() < to]
        if not rows:
            return None, None
        return max(c["high"] for c in rows), min(c["low"] for c in rows)

    pdh, pdl = extremes(yesterday, today)
    pwh, pwl = extremes(prev_week_start, week_start)
    since_today = [c for c in candles_1h if _candle_dt(c).date() >= today]
    since_week = [c for c in candles_1h if _candle_dt(c).date() >= week_start]

    def hit(level, rows, side):
        if level is None or not rows:
            return False
        return any(c["high"] > level for c in rows) if side == "h" \
            else any(c["low"] < level for c in rows)

    return {
        "pdh": pdh, "pdl": pdl, "pwh": pwh, "pwl": pwl,
        "pdh_hit": hit(pdh, since_today, "h"),
        "pdl_hit": hit(pdl, since_today, "l"),
        "pwh_hit": hit(pwh, since_week, "h"),
        "pwl_hit": hit(pwl, since_week, "l"),
    }
