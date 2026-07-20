"""Redis pub/sub event bus. Every published message is also appended to the
`events` table (when a pool is attached) — the bus archive is ground truth
for replay and audit."""
import asyncio
import json
import logging
import os

log = logging.getLogger("bus")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class Bus:
    def __init__(self, redis=None, pool=None, persist: bool = True):
        self._redis = redis
        self._pool = pool
        self._persist = persist
        self._local_subs: dict[str, list] = {}  # in-memory fallback (tests/backtest)

    @classmethod
    async def connect(cls, pool=None, persist: bool = True) -> "Bus":
        import redis.asyncio as aioredis

        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        return cls(r, pool, persist)

    async def publish(self, module: str, type_: str, payload: dict) -> None:
        msg = json.dumps({"module": module, "type": type_, "payload": payload},
                         default=str)
        if self._redis is not None:
            await self._redis.publish(type_, msg)
        for cb in self._local_subs.get(type_, []):
            await cb(payload)
        if self._persist and self._pool is not None:
            async with self._pool.acquire() as con:
                await con.execute(
                    "INSERT INTO events (module, type, payload) VALUES ($1,$2,$3::jsonb)",
                    module, type_, json.dumps(payload, default=str),
                )

    def subscribe_local(self, type_: str, callback) -> None:
        """In-process subscription — used by the worker supervisor and the
        backtest harness so both run the identical module chain."""
        self._local_subs.setdefault(type_, []).append(callback)

    async def listen(self, type_: str, callback) -> None:
        """Cross-process subscription via Redis (dashboard/api side)."""
        assert self._redis is not None, "redis not connected"
        psub = self._redis.pubsub()
        await psub.subscribe(type_)
        async for m in psub.listen():
            if m.get("type") != "message":
                continue
            try:
                data = json.loads(m["data"])
            except Exception:  # noqa: BLE001
                continue
            await callback(data.get("payload") or {})
