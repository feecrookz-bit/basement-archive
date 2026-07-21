"""Binance public-data ingestion: REST backfill + websocket kline stream into
Redis. Paper mode needs no API keys — everything here is public endpoints."""
import asyncio
import json
import logging

import aiohttp

log = logging.getLogger("ingest")

REST = "https://api.binance.com"
WS = "wss://stream.binance.com:9443/stream"
FAPI = "https://fapi.binance.com"  # public futures data for funding/OI overlay


def _parse_kline(k: list) -> dict:
    return {"ts": int(k[0]), "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}


class BinanceRest:
    def __init__(self, sess: aiohttp.ClientSession):
        self._sess = sess
        self._symbols_cache: list[str] | None = None

    async def klines(self, symbol: str, tf: str, limit: int) -> list[dict]:
        sym = symbol.replace("/", "")
        async with self._sess.get(f"{REST}/api/v3/klines", params={
                "symbol": sym, "interval": tf, "limit": min(limit, 1000)}) as r:
            r.raise_for_status()
            return [_parse_kline(k) for k in await r.json()]

    async def spread_pct(self, symbol: str) -> float | None:
        sym = symbol.replace("/", "")
        async with self._sess.get(f"{REST}/api/v3/ticker/bookTicker",
                                  params={"symbol": sym}) as r:
            if r.status != 200:
                return None
            t = await r.json()
        bid, ask = float(t.get("bidPrice") or 0), float(t.get("askPrice") or 0)
        if not bid or not ask:
            return None
        return round(100 * (ask - bid) / ((ask + bid) / 2), 4)

    async def vol_24h_usd(self, symbol: str) -> float | None:
        sym = symbol.replace("/", "")
        async with self._sess.get(f"{REST}/api/v3/ticker/24hr",
                                  params={"symbol": sym}) as r:
            if r.status != 200:
                return None
            t = await r.json()
        return float(t.get("quoteVolume") or 0)

    async def usdt_spot_symbols(self) -> list[str]:
        if self._symbols_cache is not None:
            return self._symbols_cache
        async with self._sess.get(f"{REST}/api/v3/exchangeInfo") as r:
            r.raise_for_status()
            info = await r.json()
        out = [f"{s['baseAsset']}/USDT" for s in info.get("symbols", [])
               if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
               and s.get("isSpotTradingAllowed")]
        self._symbols_cache = out
        return out

    async def funding_rates(self) -> dict[str, float]:
        """Latest funding rate per perp symbol (public futures endpoint)."""
        async with self._sess.get(f"{FAPI}/fapi/v1/premiumIndex") as r:
            if r.status != 200:
                return {}
            rows = await r.json()
        return {x["symbol"]: float(x.get("lastFundingRate") or 0)
                for x in rows if isinstance(x, dict) and x.get("symbol")}

    async def open_interest(self, symbol: str) -> float | None:
        sym = symbol.replace("/", "")
        async with self._sess.get(f"{FAPI}/fapi/v1/openInterest",
                                  params={"symbol": sym}) as r:
            if r.status != 200:
                return None
            return float((await r.json()).get("openInterest") or 0)


async def backfill(redis, rest: BinanceRest, symbols: list[str],
                   tfs: tuple[str, ...] = ("1h", "4h"), days: int = 14) -> None:
    per_tf = {"1h": days * 24, "4h": days * 6}
    for sym in symbols:
        for tf in tfs:
            try:
                data = await rest.klines(sym, tf, per_tf.get(tf, 500))
                await redis.set(f"klines:{sym}:{tf}", json.dumps(data))
            except Exception as e:  # noqa: BLE001
                log.warning("backfill %s %s failed: %s", sym, tf, e)
        await asyncio.sleep(0.1)  # stay well under REST weight limits


async def kline_stream(redis, symbols: list[str], tfs=("1h",)) -> None:
    """Combined-stream WS: append closed candles onto the Redis kline lists."""
    import websockets

    streams = "/".join(f"{s.replace('/', '').lower()}@kline_{tf}"
                       for s in symbols for tf in tfs)
    url = f"{WS}?streams={streams}"
    while True:
        try:
            async with websockets.connect(url, max_size=4_000_000) as ws:
                log.info("kline stream connected (%d streams)",
                         len(symbols) * len(tfs))
                async for raw in ws:
                    msg = json.loads(raw)
                    k = (msg.get("data") or {}).get("k") or {}
                    if not k.get("x"):  # only closed candles
                        continue
                    sym = f"{k['s'][:-4]}/USDT"
                    key = f"klines:{sym}:{k['i']}"
                    candle = {"ts": int(k["t"]), "open": float(k["o"]),
                              "high": float(k["h"]), "low": float(k["l"]),
                              "close": float(k["c"]), "volume": float(k["v"])}
                    cached = await redis.get(key)
                    series = json.loads(cached) if cached else []
                    if series and series[-1]["ts"] == candle["ts"]:
                        series[-1] = candle
                    else:
                        series.append(candle)
                    await redis.set(key, json.dumps(series[-1000:]))
        except Exception as e:  # noqa: BLE001
            log.warning("kline stream dropped (%s); reconnecting in 3s", e)
            await asyncio.sleep(3)


async def derivatives_overlay(redis, rest: BinanceRest, symbols: list[str],
                              interval_s: int = 900) -> None:
    """Funding percentile + OI change flags (data only, never signals)."""
    history: dict[str, list[float]] = {}
    oi_prev: dict[str, float] = {}
    while True:
        try:
            rates = await rest.funding_rates()
            for sym in symbols:
                perp = sym.replace("/", "")
                rate = rates.get(perp)
                if rate is None:
                    continue
                h = history.setdefault(perp, [])
                h.append(rate)
                del h[:-500]
                pct = 100 * sum(1 for x in h if x <= rate) / len(h)
                await redis.set(f"funding_pctile:{sym}", str(round(pct, 1)),
                                ex=interval_s * 2)
                oi = await rest.open_interest(sym)
                if oi and perp in oi_prev and oi_prev[perp] > 0:
                    chg = 100 * (oi - oi_prev[perp]) / oi_prev[perp]
                    await redis.set(f"oi_change:{sym}", str(round(chg, 2)),
                                    ex=interval_s * 2)
                if oi:
                    oi_prev[perp] = oi
        except Exception as e:  # noqa: BLE001
            log.warning("derivatives overlay error: %s", e)
        await asyncio.sleep(interval_s)
