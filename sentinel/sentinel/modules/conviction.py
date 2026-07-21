"""CONVICTION — the edge-quality layer between Analyst and Risk.

The Analyst emits one proposal per (pair, setup). Left alone, Risk judges
them first-come-first-served and a second setup on the same pair is rejected
as `already_in_pair` — so the 3 position slots go to whichever proposal was
seen first, not the best one. This module fixes that without touching the
risk envelope: it groups a scan's proposals by pair, scores each pair by
conviction, and returns ONE ranked primary proposal per pair, best-first.

Conviction (the three sources the operator chose):
  * confluence   — more distinct setups agreeing on a pair = higher score
  * ICT premium  — ICT carries the highest base weight and multiplies the score
  * ledger trust — each setup weighted by its own recent realized expectancy
                   (see expectancy.py); losing setups fade, winners lead.

Pure and unit-tested. One trade per pair, deliberately chosen.
"""
import logging

log = logging.getLogger("conviction")

ICT = "ict"


def _weights(cfg) -> dict:
    return cfg.get("conviction.setup_base_weights",
                   {"ict": 1.5, "breakout_retest": 1.0,
                    "rs_momentum": 1.0, "range_play": 0.9})


def score(agreeing: list[str], expectancy: dict, cfg) -> float:
    """Conviction score for a set of setups agreeing on one pair."""
    base = _weights(cfg)
    contrib = 0.0
    for s in agreeing:
        contrib += base.get(s, 1.0) * expectancy.get(s, 1.0)
    if contrib <= 0:
        return 0.0
    n = len(agreeing)
    if n >= 2:
        contrib *= 1 + cfg.get("conviction.confluence_bonus", 0.4) * (n - 1)
    if ICT in agreeing:
        contrib *= cfg.get("conviction.ict_premium", 1.25)
    return round(contrib, 4)


def _best_rr(p: dict) -> float:
    t = (p.get("targets") or [{}])[0]
    return t.get("r_multiple") or 0.0


def _primary(props: list[dict]) -> dict:
    """Pick the proposal whose entry/stop/targets the trade will use: the ICT
    one if it fired (premium signal), else the best first-target R:R."""
    ict = [p for p in props if p.get("setup_type") == ICT]
    if ict:
        return max(ict, key=_best_rr)
    return max(props, key=_best_rr)


def rank(proposals: list[dict], expectancy: dict, cfg) -> list[dict]:
    """Group by pair -> conviction-scored primary proposals, best-first.

    `expectancy` maps setup_type -> multiplier (neutral 1.0). When
    `negative_expectancy_gate` is on, setups whose multiplier has collapsed to
    the clamp floor (ledger says they lose) are dropped from the agreeing set —
    but never the last one, so a pair with only a muted setup still trades at
    reduced conviction rather than vanishing silently.
    """
    if not cfg.get("conviction.enabled", True):
        # passthrough: neutral conviction, original order
        for p in proposals:
            p.setdefault("conviction", 1.0)
        return proposals

    by_pair: dict[str, list[dict]] = {}
    for p in proposals:
        by_pair.setdefault(p["pair"], []).append(p)

    gate = cfg.get("conviction.expectancy.negative_expectancy_gate", True)
    floor = (cfg.get("conviction.expectancy.clamp", [0.25, 2.0]) or [0.25])[0]

    ranked: list[dict] = []
    for pair, props in by_pair.items():
        setups = [p["setup_type"] for p in props]
        agreeing = setups
        if gate:
            kept = [s for s in setups if expectancy.get(s, 1.0) > floor]
            agreeing = kept or setups  # never drop the last one
            props = [p for p in props if p["setup_type"] in agreeing] or props
        conv = score(agreeing, expectancy, cfg)
        primary = dict(_primary(props))
        ev = dict(primary.get("evidence") or {})
        ev["conviction"] = conv
        ev["agreeing_setups"] = sorted(set(agreeing))
        ev["setup_expectancy"] = {s: round(expectancy.get(s, 1.0), 3)
                                  for s in set(setups)}
        primary["evidence"] = ev
        primary["conviction"] = conv
        primary["agreeing_setups"] = sorted(set(agreeing))
        ranked.append(primary)

    ranked.sort(key=lambda p: p["conviction"], reverse=True)
    if ranked:
        log.info("conviction ranking: %s",
                 ", ".join(f"{p['pair']}={p['conviction']}"
                           f"({'+'.join(p['agreeing_setups'])})"
                           for p in ranked[:5]))
    return ranked
