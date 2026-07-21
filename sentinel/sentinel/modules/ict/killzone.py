"""Kill zones — session-timing discipline for the ICT setup class.

"5 hours of opportunity, 19 hours of patience. The patience IS the edge."
ICT entries are only taken inside defined kill-zone windows (London KZ and
the NY-AM follow-through by default); the Asian session is observation only
— ranges get marked, nothing gets bought. Within London, the three macro
windows are tracked and the 2:33–3:00 golden window can carry a small,
bounded conviction bonus.

Pure functions of (now, cfg) — the caller passes market.now(), so backtests
replay the same gate the live worker enforces. All windows are UTC and
support midnight wrap.
"""
from datetime import datetime, time, timedelta

DEFAULT_WINDOWS = {          # UTC. London KZ = 2–5 AM New York (~07–10 UTC);
    "london": {"start": "07:00", "end": "10:00"},   # the money zone
    "ny_am": {"start": "13:30", "end": "15:00"},    # follow-through only
}
DEFAULT_MACROS = {           # inside London KZ
    "macro1": {"start": "07:00", "end": "07:15"},   # first sweep possible
    "golden": {"start": "07:33", "end": "08:00"},   # most sweeps/reversals
    "macro3": {"start": "09:00", "end": "09:15"},   # last chance, lower RR
}


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _in_window(now_t: time, win: dict) -> bool:
    start, end = _t(win["start"]), _t(win["end"])
    if start <= end:
        return start <= now_t < end
    return now_t >= start or now_t < end  # crosses midnight


def enabled(cfg) -> bool:
    return bool(cfg.get("ict.killzones.enabled", True))


def state(now: datetime, cfg) -> dict:
    """{'active', 'zone', 'macro_window', 'next_open_utc'} for `now` (UTC)."""
    windows = cfg.get("ict.killzones.windows") or DEFAULT_WINDOWS
    macros = cfg.get("ict.killzones.macro_windows") or DEFAULT_MACROS
    now_t = now.time().replace(second=0, microsecond=0)

    zone = next((name for name, win in windows.items()
                 if _in_window(now_t, win)), None)
    macro = next((name for name, win in macros.items()
                  if _in_window(now_t, win)), None) if zone else None

    next_open = None
    if zone is None and windows:
        candidates = []
        for win in windows.values():
            start = datetime.combine(now.date(), _t(win["start"]),
                                     tzinfo=now.tzinfo)
            if start <= now:
                start += timedelta(days=1)
            candidates.append(start)
        next_open = min(candidates).strftime("%H:%M")

    return {"active": zone is not None, "zone": zone, "macro_window": macro,
            "next_open_utc": next_open}


def entries_allowed(now: datetime, cfg) -> bool:
    """The gate: outside a kill zone, ICT proposes nothing. Disabled ⇒ 24/7
    (crypto never closes; the discipline is opt-out, not physics)."""
    if not enabled(cfg):
        return True
    return state(now, cfg)["active"]


def golden_multiplier(evidence: dict, cfg) -> float:
    """Bounded conviction bonus when the entry fired in the golden window."""
    if not enabled(cfg):
        return 1.0
    if (evidence or {}).get("killzone", {}).get("macro_window") == "golden":
        return 1.0 + max(0.0, min(0.5, cfg.get("ict.killzones.golden_bonus",
                                               0.15)))
    return 1.0
