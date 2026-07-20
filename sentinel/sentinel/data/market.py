"""MarketState — the single data interface every module reads through.

LiveMarket serves from Redis (populated by ingest) with REST fallback.
ReplayMarket serves preloaded candles behind a simulated clock cursor.
Modules cannot tell them apart, which is what makes the backtest replay the
exact production code path.
"""
import json
import time
from datetime import datetime, timezone

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
         "4h": 14_400_000, "1d": 86_400_000}


class LiveMarket:
    def __init__(self, redis, rest):
        self._redis = redis
        self._rest = rest  # BinanceRest from ingest.py

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def candles(self, symbol: str, tf: str, n: int) -> list[dict]:
        raw = await self._redis.get(f"klines:{symbol}:{tf}")
        if raw:
            data = json.loads(raw)
            if len(data) >= n:
                return data[-n:]
        data = await self._rest.klines(symbol, tf, n)
        await self._redis.set(f"klines:{symbol}:{tf}", json.dumps(data),
                              ex=TF_MS[tf] // 1000)
        return data[-n:]

    async def last_price(self, symbol: str) -> float | None:
        c = await self.candles(symbol, "1m", 1)
        return c[-1]["close"] if c else None

    async def spread_pct(self, symbol: str) -> float | None:
        return await self._rest.spread_pct(symbol)

    async def vol_24h_usd(self, symbol: str) -> float | None:
        raw = await self._redis.get(f"ticker24:{symbol}")
        if raw:
            return float(raw)
        return await self._rest.vol_24h_usd(symbol)

    async def universe(self) -> list[str]:
        return await self._rest.usdt_spot_symbols()

    async def funding_pctile(self, symbol: str) -> float | None:
        raw = await self._redis.get(f"funding_pctile:{symbol}")
        return float(raw) if raw else None

    async def oi_change_pct(self, symbol: str, hours: int = 4) -> float | None:
        raw = await self._redis.get(f"oi_change:{symbol}")
        return float(raw) if raw else None


class ReplayMarket:
    """Backtest feed: candle dict per (symbol, tf), advanced by a cursor.

    `candles` returns only data at or before the simulated now — the modules
    literally cannot look ahead.
    """

    def __init__(self, series: dict[tuple[str, str], list[dict]],
                 universe: list[str] | None = None,
                 spreads: dict[str, float] | None = None,
                 vols_24h: dict[str, float] | None = None):
        self._series = series
        self._universe = universe or sorted({s for s, _ in series})
        self._spreads = spreads or {}
        self._vols = vols_24h or {}
        self._now_ms: int = min(s[0]["ts"] for s in series.values() if s)

    def set_now_ms(self, ts_ms: int) -> None:
        self._now_ms = ts_ms

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._now_ms / 1000, tz=timezone.utc)

    async def candles(self, symbol: str, tf: str, n: int) -> list[dict]:
        data = self._series.get((symbol, tf), [])
        visible = [c for c in data if c["ts"] <= self._now_ms]
        return visible[-n:]

    async def last_price(self, symbol: str) -> float | None:
        for tf in ("1m", "5m", "15m", "1h"):
            c = await self.candles(symbol, tf, 1)
            if c:
                return c[-1]["close"]
        return None

    async def spread_pct(self, symbol: str) -> float | None:
        return self._spreads.get(symbol, 0.05)

    async def vol_24h_usd(self, symbol: str) -> float | None:
        return self._vols.get(symbol, 50_000_000)

    async def universe(self) -> list[str]:
        return self._universe

    async def funding_pctile(self, symbol: str) -> float | None:
        return None

    async def oi_change_pct(self, symbol: str, hours: int = 4) -> float | None:
        return None
