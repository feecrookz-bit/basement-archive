"""ICT agent — Sentinel's fourth setup class (config-gated: ict.enabled).

Runs inside the Analyst pass, on the watchlist, only when Regime permits.
Proposals carry setup_type="ict" and flow through the identical Risk veto,
paper Executor, and Coach analytics as the other three setups — the ledger
decides whether ICT earns, not the aesthetics of the chart."""
import json
import logging

from . import killzone as kz
from . import sessions as sx
from . import setup as ict_setup

log = logging.getLogger("ict")


async def snapshot_state(ledger, pair: str, sess: dict, levels: dict,
                         zones: dict, config_version_id) -> None:
    ins = getattr(ledger, "insert_ict_snapshot", None)
    if ins is not None:
        await ins(pair, sess, levels, zones, config_version_id)


async def scan(market, ledger, bus, cfg, regime_snap: dict,
               watchlist: dict) -> list[dict]:
    """One ICT pass over the watchlist. Returns persisted proposals."""
    if not cfg.get("ict.enabled", True):
        return []
    tf = cfg.get("ict.timeframe", "15m")
    now = market.now()
    kz_state = kz.state(now, cfg)
    gate_open = kz.entries_allowed(now, cfg)
    if not gate_open:
        log.debug("outside kill zones (next opens %s UTC) — observing only",
                  kz_state.get("next_open_utc"))
    ref_pair = cfg.get("ict.smt_reference", "BTC/USDT")
    ref_15m = await market.candles(ref_pair, tf, 200)
    proposals: list[dict] = []
    for entry in watchlist.get("entries", []):
        pair = entry["pair"]
        if entry.get("flags", {}).get("unlock_blacklist"):
            continue
        c15 = await market.candles(pair, tf, 200)
        if len(c15) < 40:
            continue
        c1h = await market.candles(pair, "1h", 24 * 15)
        sess = sx.session_state(c15, now, cfg.get("ict.sessions"))
        levels = sx.day_levels(c1h, now)

        from . import concepts as cx
        atr_now = cx.atr(c15)
        zones = {
            "fvgs": [g for g in cx.fvgs(c15[-60:], atr_now,
                                        cfg.get("ict.fvg_min_atr_frac", 0.25))
                     if not g["filled"]][-6:],
            "order_blocks": cx.order_blocks(
                c15[-60:], atr_now,
                cfg.get("ict.displacement_atr_mult", 1.5))[-4:],
        }
        await snapshot_state(ledger, pair, sess, levels, zones, cfg.version_id)

        if not gate_open:
            continue  # kill-zone discipline: mark levels, take nothing
        p = ict_setup.detect(c15, ref_15m, sess, levels, entry, cfg)
        if not p:
            continue
        p["evidence"]["killzone"] = kz_state
        p.update({
            "pair": pair, "setup_type": "ict", "side": "long",
            "regime_snapshot_id": regime_snap["id"],
            "watchlist_id": watchlist.get("id"),
            "config_version_id": cfg.version_id,
        })
        p["id"] = await ledger.insert_proposal(p)
        await bus.publish("analyst", "analyst.proposal", p)
        ev = p["evidence"]
        log.info("ICT proposal #%s %s sweep=%s via=%s rr=%.1f smt=%s",
                 p["id"], pair, ev["sweep"]["label"], ev["entered_via"],
                 ev["rr_first_target"], ev["smt_divergence"])
        proposals.append(p)
    return proposals


def _json(o):  # small helper for snapshot serialization callers
    return json.dumps(o, default=str)
