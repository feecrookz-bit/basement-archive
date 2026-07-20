"""REGIME — the tide-reader. Decides whether trading is allowed at all.

Pure classification over BTC candles; the tick loop persists a snapshot and
publishes it on the bus every refresh. Only states in
regime.states_allowing_entries permit alt long entries; VOLATILE_CHOP is
mandatory flat. Kill conditions (BTC 1h move, crowded funding) override
everything.
"""
import logging

from .. import indicators as ind

log = logging.getLogger("regime")

TRENDING_UP = "TRENDING_UP"
TRENDING_UP_EARLY = "TRENDING_UP_EARLY"
RANGING = "RANGING"
TRENDING_DOWN = "TRENDING_DOWN"
VOLATILE_CHOP = "VOLATILE_CHOP"


def classify(candles_1h: list[dict], candles_4h: list[dict], cfg) -> dict:
    """Pure: BTC state + kill flags from candle data alone."""
    closes_1h = [c["close"] for c in candles_1h]
    closes_4h = [c["close"] for c in candles_4h]
    emas = {}
    for tf, closes in (("1h", closes_1h), ("4h", closes_4h)):
        emas[tf] = {}
        for p in cfg.get("regime.emas", [20, 50, 200]):
            series = ind.ema(closes, p)
            emas[tf][f"ema{p}"] = series[-1] if series else None
        emas[tf]["close"] = closes[-1] if closes else None

    e1 = emas["1h"]
    e4 = emas["4h"]
    atr_now = ind.atr(candles_1h)
    atr_hist = ind.atr_series(candles_1h)
    atr_pct = ind.percentile_rank(atr_hist, atr_now, strict=True) if atr_now else None
    rvol = ind.realized_vol(closes_1h, 24)
    move_1h = None
    if len(closes_1h) >= 2 and closes_1h[-2]:
        move_1h = round(100 * (closes_1h[-1] - closes_1h[-2]) / closes_1h[-2], 3)

    complete = all(e1.get(k) for k in ("ema20", "ema50", "ema200", "close")) \
        and all(e4.get(k) for k in ("ema50", "close"))

    state = RANGING
    if complete:
        # EMAs must be meaningfully separated, not just noise-ordered:
        # near-equal EMAs on a flat tape are RANGING, not a trend.
        eps = 1 + cfg.get("regime.ema_alignment_min_separation_pct", 0.1) / 100
        up_aligned = e1["close"] > e1["ema20"] > e1["ema50"] * eps \
            and e1["ema50"] > e1["ema200"] * eps and e4["close"] > e4["ema50"]
        down_aligned = e1["close"] < e1["ema20"] < e1["ema50"] / eps \
            and e1["ema50"] < e1["ema200"] / eps and e4["close"] < e4["ema50"]
        high_vol = atr_pct is not None and atr_pct >= 80
        if up_aligned:
            ext_limit = cfg.get("regime.trending_up_early_max_atr_extension", 2.0)
            extension = ((e1["close"] - e1["ema20"]) / atr_now) if atr_now else 0
            state = TRENDING_UP_EARLY if extension <= ext_limit else TRENDING_UP
        elif down_aligned:
            state = TRENDING_DOWN
        elif high_vol:
            state = VOLATILE_CHOP
        else:
            state = RANGING

    kill_flags = []
    kill_move = cfg.get("regime.kill.btc_1h_move_pct", 3.0)
    if move_1h is not None and abs(move_1h) > kill_move:
        kill_flags.append("btc_1h_move")

    allowed_states = cfg.get("regime.states_allowing_entries",
                             [RANGING, TRENDING_UP_EARLY])
    trading_allowed = state in allowed_states and not kill_flags

    return {
        "btc_state": state,
        "trading_allowed": trading_allowed,
        "ema_structure": emas,
        "atr_percentile": atr_pct,
        "realized_vol_24h": rvol,
        "btc_move_1h_pct": move_1h,
        "kill_flags": kill_flags,
    }


async def tick(market, ledger, bus, cfg, funding_pctile: float | None = None) -> dict:
    """One refresh cycle: classify, persist, publish. Returns the snapshot."""
    candles_1h = await market.candles("BTC/USDT", "1h", 250)
    candles_4h = await market.candles("BTC/USDT", "4h", 250)
    snap = classify(candles_1h, candles_4h, cfg)
    if funding_pctile is None:
        funding_pctile = await market.funding_pctile("BTC/USDT")
    extreme = cfg.get("regime.kill.funding_extreme_percentile", 95)
    if funding_pctile is not None and funding_pctile >= extreme:
        snap["kill_flags"].append("funding_crowded")
        snap["trading_allowed"] = False
    snap["config_version_id"] = cfg.version_id
    snap["id"] = await ledger.insert_regime(snap)
    await bus.publish("regime", "regime.tick", snap)
    log.info("regime: %s allowed=%s flags=%s", snap["btc_state"],
             snap["trading_allowed"], snap["kill_flags"])
    return snap
