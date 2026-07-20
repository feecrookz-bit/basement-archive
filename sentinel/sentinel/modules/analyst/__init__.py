"""ANALYST — setup detection. Exactly three setups, no more.

Runs only on Scout's watchlist, only when Regime permits. Each setup is a
pure detector: candles + config in, proposal dict (or None) out. The
dispatcher stamps proposals with the regime/watchlist snapshot ids and the
config version, persists, and publishes for Risk to judge.
"""
import logging

from . import breakout_retest, range_play, rs_momentum

log = logging.getLogger("analyst")

DETECTORS = {
    "range_play": range_play.detect,
    "breakout_retest": breakout_retest.detect,
    "rs_momentum": rs_momentum.detect,
}


async def scan(market, ledger, bus, cfg, regime_snap: dict,
               watchlist: dict) -> list[dict]:
    """One pass over the watchlist. Returns persisted proposals."""
    if not regime_snap.get("trading_allowed"):
        return []
    tf = cfg.get("analyst.candle_tf", "1h")
    proposals = []
    for entry in watchlist.get("entries", []):
        if entry.get("flags", {}).get("unlock_blacklist"):
            continue  # no longs into a supply unlock
        candles = await market.candles(entry["pair"], tf, 200)
        if len(candles) < 60:
            continue
        for name, detect in DETECTORS.items():
            if not cfg.get(f"analyst.setups.{name}.enabled", True):
                continue
            p = detect(candles, entry, cfg)
            if not p:
                continue
            p.update({
                "pair": entry["pair"], "setup_type": name, "side": "long",
                "regime_snapshot_id": regime_snap["id"],
                "watchlist_id": watchlist.get("id"),
                "config_version_id": cfg.version_id,
            })
            p["id"] = await ledger.insert_proposal(p)
            await bus.publish("analyst", "analyst.proposal", p)
            log.info("proposal #%s %s %s entry=%.6g stop=%.6g", p["id"],
                     name, entry["pair"], p["entry_price"], p["stop_price"])
            proposals.append(p)
    return proposals
