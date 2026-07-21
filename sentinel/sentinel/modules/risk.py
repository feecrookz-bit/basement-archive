"""RISK — the veto. Strategy modules propose; this module disposes.

Everything here is a hard rule. The sizing formula derives quantity from
stop distance — never the reverse. Circuit breakers flatten and halt.
There is no martingale, no averaging down, no doubling after losses:
those are not configurable and will not be implemented.
"""
import logging
from dataclasses import dataclass, field

log = logging.getLogger("risk")


@dataclass
class AccountState:
    """Inputs the veto needs; the caller assembles it from ledger + equity."""
    equity: float
    open_positions: list[dict] = field(default_factory=list)
    # each: {pair, sector, risk_quote}
    entries_last_24h: int = 0
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    halted: bool = False


def sector_of(pair: str, cfg) -> str | None:
    base = pair.split("/")[0].upper()
    for sector, members in (cfg.get("risk.sectors") or {}).items():
        if base in [m.upper() for m in members]:
            return sector
    return None


def size_position(equity: float, risk_pct: float, entry: float, stop: float) -> dict | None:
    """size = (equity * risk_per_trade) / (entry - stop). Stop drives size."""
    if entry <= stop or equity <= 0:
        return None
    risk_quote = equity * risk_pct / 100
    qty = risk_quote / (entry - stop)
    return {"qty": round(qty, 8), "notional": round(qty * entry, 2),
            "risk_quote": round(risk_quote, 2), "risk_pct": risk_pct,
            "equity_at_decision": equity}


def conviction_risk_pct(conviction: float | None, cfg) -> float:
    """Scale base risk by conviction, bounded. Edge quality, not aggression:
    the multiplier is clamped and the hard open-risk cap still governs, so a
    high-conviction trade sizes up modestly while the average stays disciplined.
    Conviction ~1.0 is neutral; the scale saturates at max_mult."""
    base = cfg.get("risk.risk_per_trade_pct", 0.75)
    if not cfg.get("conviction.sizing.enabled", True) or conviction is None:
        return base
    lo = cfg.get("conviction.sizing.min_mult", 0.8)
    hi = cfg.get("conviction.sizing.max_mult", 1.5)
    pivot = cfg.get("conviction.sizing.pivot", 1.5)  # conviction that maps to 1.0x
    mult = max(lo, min(hi, conviction / pivot))
    return round(base * mult, 4)


def evaluate(proposal: dict, state: AccountState, cfg) -> dict:
    """Pure veto. Returns {decision, reject_reasons, sizing}."""
    reasons: list[str] = []

    if state.halted:
        reasons.append("halt_active")

    daily_stop = cfg.get("risk.circuit_breakers.daily_loss_pct", 2.0)
    if state.daily_pnl_pct <= -daily_stop:
        reasons.append(f"daily_breaker:{state.daily_pnl_pct:.2f}%")
    weekly_stop = cfg.get("risk.circuit_breakers.weekly_loss_pct", 5.0)
    if state.weekly_pnl_pct <= -weekly_stop:
        reasons.append(f"weekly_breaker:{state.weekly_pnl_pct:.2f}%")

    max_concurrent = cfg.get("risk.max_concurrent_positions", 3)
    if len(state.open_positions) >= max_concurrent:
        reasons.append(f"max_concurrent:{len(state.open_positions)}")

    governor = cfg.get("risk.overtrading_governor.max_new_entries_per_24h", 4)
    if state.entries_last_24h >= governor:
        reasons.append(f"overtrading_governor:{state.entries_last_24h}/24h")

    sector = sector_of(proposal["pair"], cfg)
    per_sector = cfg.get("risk.max_positions_per_sector", 1)
    if sector:
        held = sum(1 for p in state.open_positions if p.get("sector") == sector)
        if held >= per_sector:
            reasons.append(f"sector_cap:{sector}")
    if any(p["pair"] == proposal["pair"] for p in state.open_positions):
        reasons.append("already_in_pair")  # adding to a position = averaging; banned

    sizing = size_position(state.equity,
                           conviction_risk_pct(proposal.get("conviction"), cfg),
                           proposal["entry_price"], proposal["stop_price"])
    if sizing is None:
        reasons.append("invalid_entry_stop")
    else:
        open_risk = sum(p.get("risk_quote", 0) for p in state.open_positions)
        max_open = cfg.get("risk.max_total_open_risk_pct", 2.0) * state.equity / 100
        if open_risk + sizing["risk_quote"] > max_open:
            reasons.append(f"max_open_risk:{open_risk + sizing['risk_quote']:.2f}"
                           f">{max_open:.2f}")
        if sector:
            sizing["sector"] = sector

    if reasons:
        return {"decision": "rejected", "reject_reasons": reasons, "sizing": None}
    return {"decision": "accepted", "reject_reasons": None, "sizing": sizing}


def breaker_check(state: AccountState, cfg) -> dict | None:
    """Independent of proposals: does equity demand a halt right now?
    Returns a halt dict or None. Called every executor cycle."""
    daily_stop = cfg.get("risk.circuit_breakers.daily_loss_pct", 2.0)
    weekly_stop = cfg.get("risk.circuit_breakers.weekly_loss_pct", 5.0)
    if state.weekly_pnl_pct <= -weekly_stop:
        return {"scope": "weekly", "flatten": True,
                "reason": f"weekly equity {state.weekly_pnl_pct:.2f}% <= -{weekly_stop}%; "
                          f"halt until manual restart with typed confirmation"}
    if state.daily_pnl_pct <= -daily_stop:
        return {"scope": "daily", "flatten": True,
                "reason": f"daily equity {state.daily_pnl_pct:.2f}% <= -{daily_stop}%; "
                          f"no new entries for "
                          f"{cfg.get('risk.circuit_breakers.daily_halt_hours', 24)}h"}
    return None


async def judge(proposal: dict, state: AccountState, ledger, bus, cfg) -> dict:
    """Evaluate, persist the decision, publish accepted proposals to executor."""
    verdict = evaluate(proposal, state, cfg)
    await ledger.insert_decision(proposal["id"], verdict["decision"],
                                 verdict["reject_reasons"], verdict["sizing"])
    if verdict["decision"] == "rejected":
        log.info("REJECT #%s %s: %s", proposal["id"], proposal["pair"],
                 ", ".join(verdict["reject_reasons"]))
        await bus.publish("risk", "risk.rejected",
                          {"proposal": proposal,
                           "reasons": verdict["reject_reasons"]})
    else:
        log.info("ACCEPT #%s %s qty=%s risk=%s", proposal["id"], proposal["pair"],
                 verdict["sizing"]["qty"], verdict["sizing"]["risk_quote"])
        await bus.publish("risk", "risk.accepted",
                          {"proposal": proposal, "sizing": verdict["sizing"]})
    return verdict
