"""Decision memos — one clear, human-readable verdict per proposal.

The engine already decides; this module *presents* the decision the way an
operator reads it: setup summary, signal strength, risk level, trade plan,
final status. Three statuses:

- APPROVED   — passed the veto, trade opened (paper or live)
- WATCHLIST  — good setup, no capacity: every reject reason is a capacity
               cap (slots, sector, open-risk budget, governor). Monitor it.
- REJECTED   — quality/safety fail (breaker, halt, volatility, bad levels).

Pure functions; the memo is published on the bus (persisted in events) and
served at /api/memos.
"""

# capacity caps — the setup was fine, the book was full
WATCHLIST_PREFIXES = ("max_concurrent", "overtrading_governor", "sector_cap",
                      "max_open_risk", "already_in_pair")


def status_of(verdict: dict) -> str:
    if verdict["decision"] == "accepted":
        return "APPROVED"
    reasons = verdict.get("reject_reasons") or []
    if reasons and all(r.startswith(WATCHLIST_PREFIXES) for r in reasons):
        return "WATCHLIST"
    return "REJECTED"


def stars(conviction: float | None) -> int:
    """Conviction → 1–5 signal-strength stars (pivot 1.5 ≈ 3 stars)."""
    if conviction is None:
        return 3
    for threshold, s in ((0.75, 1), (1.25, 2), (1.75, 3), (2.5, 4)):
        if conviction < threshold:
            return s
    return 5


def risk_rating(sizing: dict | None, cfg) -> str:
    base = cfg.get("risk.risk_per_trade_pct", 0.75)
    pct = (sizing or {}).get("risk_pct", base)
    if pct < base * 0.95:
        return "LOW"
    if pct > base * 1.2:
        return "ELEVATED"
    return "MODERATE"


def compose(proposal: dict, verdict: dict, cfg) -> dict:
    ev = proposal.get("evidence") or {}
    targets = proposal.get("targets") or []
    first_target = (targets[0] or {}) if targets else {}
    conviction = ev.get("conviction")
    return {
        "pair": proposal.get("pair"),
        "setup_type": proposal.get("setup_type"),
        "side": proposal.get("side", "long"),
        "status": status_of(verdict),
        "reasons": verdict.get("reject_reasons") or [],
        "signal": {
            "conviction": conviction,
            "stars": stars(conviction),
            "agreeing_setups": ev.get("agreeing_setups") or
                               [proposal.get("setup_type")],
        },
        "risk": {
            "rating": risk_rating(verdict.get("sizing"), cfg),
            "risk_pct": (verdict.get("sizing") or {}).get(
                "risk_pct", cfg.get("risk.risk_per_trade_pct", 0.75)),
        },
        "plan": {
            "entry": proposal.get("entry_price"),
            "stop": proposal.get("stop_price"),
            "target": first_target.get("price"),
            "rr": ev.get("rr_first_target") or first_target.get("r_multiple"),
        },
    }


def render_text(memo: dict) -> str:
    """Compact text form for logs/notifications."""
    star_bar = "★" * memo["signal"]["stars"] + "☆" * (5 - memo["signal"]["stars"])
    plan = memo["plan"]
    lines = [
        f"{memo['status']} — {memo['pair']} {memo['setup_type']} ({memo['side']})",
        f"signal {star_bar} · risk {memo['risk']['rating']} "
        f"({memo['risk']['risk_pct']}%)",
        f"entry {plan['entry']} · stop {plan['stop']} · target {plan['target']}"
        + (f" · R:R {plan['rr']}" if plan.get("rr") else ""),
    ]
    if memo["reasons"]:
        lines.append("reasons: " + ", ".join(memo["reasons"]))
    return "\n".join(lines)
