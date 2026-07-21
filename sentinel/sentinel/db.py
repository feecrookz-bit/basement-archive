"""asyncpg pool + idempotent schema application from schema.sql."""
import os
from pathlib import Path

import asyncpg

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentinel"
)

_pool: asyncpg.Pool | None = None


async def init() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8)
    async with _pool.acquire() as con:
        await con.execute(SCHEMA_PATH.read_text())
    return _pool


async def close() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "db.init() not called"
    return _pool
