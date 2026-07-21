"""asyncpg pool + schema. Idempotent init on startup."""
import asyncpg
from . import config

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    chain_id      TEXT NOT NULL,
    token_address TEXT NOT NULL,
    source        TEXT NOT NULL,
    description   TEXT,
    url           TEXT,
    icon          TEXT,
    boost_amount  DOUBLE PRECISION,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, token_address)
);

CREATE TABLE IF NOT EXISTS tracked_wallets (
    wallet    TEXT PRIMARY KEY,
    label     TEXT,
    weight    DOUBLE PRECISION NOT NULL DEFAULT 1.0,  -- quality multiplier, auto-tuned 0.25..3.0
    wins      INT NOT NULL DEFAULT 0,
    losses    INT NOT NULL DEFAULT 0,
    added_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wallet_hits (
    id            BIGSERIAL PRIMARY KEY,
    wallet        TEXT NOT NULL,
    chain_id      TEXT NOT NULL DEFAULT 'solana',
    token_address TEXT NOT NULL,
    side          TEXT NOT NULL,            -- buy | sell
    sol_amount    DOUBLE PRECISION,         -- approx SOL notional of the swap
    tx_sig        TEXT,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tx_sig, token_address, side)
);

-- Safety-check snapshot per token (refreshed on demand)
CREATE TABLE IF NOT EXISTS token_checks (
    token_address   TEXT PRIMARY KEY,
    liquidity_usd   DOUBLE PRECISION,
    volume_h1_usd   DOUBLE PRECISION,
    fdv_usd         DOUBLE PRECISION,
    price_usd       DOUBLE PRECISION,
    pair_address    TEXT,
    pair_created_at TIMESTAMPTZ,
    mint_revoked    BOOLEAN,
    freeze_revoked  BOOLEAN,
    top10_pct       DOUBLE PRECISION,
    passed          BOOLEAN,
    fail_reasons    TEXT,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
    id            BIGSERIAL PRIMARY KEY,
    chain_id      TEXT NOT NULL,
    token_address TEXT NOT NULL,
    wallet        TEXT NOT NULL,
    reason        TEXT NOT NULL,
    score         DOUBLE PRECISION NOT NULL,
    gated         BOOLEAN NOT NULL DEFAULT false,   -- true = passed all safety gates
    ts            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Loss-inclusive paper ledger: every gated signal gets a hypothetical entry.
CREATE TABLE IF NOT EXISTS paper_trades (
    id             BIGSERIAL PRIMARY KEY,
    signal_id      BIGINT REFERENCES signals(id),
    token_address  TEXT NOT NULL,
    trigger_wallet TEXT NOT NULL,
    entry_price    DOUBLE PRECISION NOT NULL,
    stake_sol      DOUBLE PRECISION NOT NULL,
    peak_price     DOUBLE PRECISION,
    exit_price     DOUBLE PRECISION,
    pnl_pct        DOUBLE PRECISION,                -- net of assumed slippage
    status         TEXT NOT NULL DEFAULT 'open',    -- open | tp | sl | timeout | dead
    opened_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at      TIMESTAMPTZ
);

ALTER TABLE signals      ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'momentum';
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'momentum';
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS peak_x DOUBLE PRECISION;

-- v2.2: Method-3 snapshot data on token_checks
ALTER TABLE token_checks ADD COLUMN IF NOT EXISTS buys_h1  INT;
ALTER TABLE token_checks ADD COLUMN IF NOT EXISTS sells_h1 INT;
ALTER TABLE token_checks ADD COLUMN IF NOT EXISTS volume_m5_usd DOUBLE PRECISION;
ALTER TABLE token_checks ADD COLUMN IF NOT EXISTS holder_count INT;
ALTER TABLE token_checks ADD COLUMN IF NOT EXISTS holder_count_prev INT;

-- v2.2: Binance touchpoints on tokens we care about (exit-liquidity events)
CREATE TABLE IF NOT EXISTS binance_events (
    id            BIGSERIAL PRIMARY KEY,
    token_address TEXT NOT NULL,
    symbol        TEXT,
    event_type    TEXT NOT NULL,           -- alpha | announcement
    title         TEXT,
    url           TEXT,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (token_address, event_type, title)
);

-- v2.2: pump.fun graduations and the dump->reclaim state machine
CREATE TABLE IF NOT EXISTS graduations (
    token_address TEXT PRIMARY KEY,
    migrated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    grad_price    DOUBLE PRECISION,
    low_price     DOUBLE PRECISION,
    reclaimed     BOOLEAN NOT NULL DEFAULT false,
    reclaimed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tokens_first_seen ON tokens (first_seen DESC);
CREATE INDEX IF NOT EXISTS idx_hits_ts    ON wallet_hits (ts DESC);
CREATE INDEX IF NOT EXISTS idx_hits_token ON wallet_hits (token_address, side, ts DESC);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals (ts DESC);
CREATE INDEX IF NOT EXISTS idx_paper_open ON paper_trades (status) WHERE status = 'open';
"""

async def init() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=8)
    async with _pool.acquire() as con:
        await con.execute(SCHEMA)
    return _pool

async def close() -> None:
    if _pool:
        await _pool.close()

def pool() -> asyncpg.Pool:
    assert _pool is not None, "db.init() not called"
    return _pool
