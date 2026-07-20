-- =============================================================================
-- SENTINEL — event-sourced schema (PostgreSQL 16)
-- =============================================================================
-- Principles encoded here:
--   * APPEND-ONLY. No UPDATE/DELETE on ledger tables, ever. State transitions
--     are new rows (events); current state is a fold over events, exposed via
--     views. The only mutable-looking things are materialized read models the
--     app may rebuild from events at any time.
--   * Every decision carries its full evidence: proposals embed the complete
--     indicator/regime snapshot and the config version that produced them, so
--     any trade can be reconstructed exactly.
--   * The paper->live gate is enforceable from this schema alone (see
--     v_paper_readiness at the bottom).
-- =============================================================================

-- ---------- config versioning (every trade references one) -------------------
CREATE TABLE IF NOT EXISTS config_versions (
    id           BIGSERIAL PRIMARY KEY,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    content      JSONB NOT NULL,          -- full parsed config.yaml
    content_hash TEXT  NOT NULL,          -- sha256 of canonical yaml
    UNIQUE (content_hash)
);

-- ---------- master event log (the bus archive) --------------------------------
-- Everything published on Redis pub/sub is also appended here. Typed tables
-- below are queryable projections of the subset that matters; this is the
-- ground truth for replay/audit.
CREATE TABLE IF NOT EXISTS events (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    module  TEXT NOT NULL,       -- regime | scout | analyst | risk | executor | coach | system
    type    TEXT NOT NULL,       -- e.g. regime.tick, scout.watchlist, analyst.proposal, risk.reject
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (type, ts DESC);

-- ---------- REGIME ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    btc_state         TEXT NOT NULL,      -- TRENDING_UP | RANGING | TRENDING_DOWN | VOLATILE_CHOP
    trading_allowed   BOOLEAN NOT NULL,   -- derived: state in allowed set AND no kill flags
    ema_structure     JSONB NOT NULL,     -- {tf: {ema20, ema50, ema200, close}} for 1h + 4h
    atr_percentile    DOUBLE PRECISION,
    realized_vol_24h  DOUBLE PRECISION,
    btc_move_1h_pct   DOUBLE PRECISION,
    kill_flags        JSONB NOT NULL DEFAULT '[]',  -- ["btc_1h_move", "funding_crowded", ...]
    config_version_id BIGINT NOT NULL REFERENCES config_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_snapshots (ts DESC);

-- ---------- SCOUT -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    entries           JSONB NOT NULL,
    -- entries: [{pair, rs_score, rs_4h, rs_24h, rs_72h, higher_lows_vs_btc,
    --            vol_24h_usd, spread_pct, flags: {unlock_blacklist, funding_extreme,
    --            oi_loading}, rank}]
    universe_size     INT NOT NULL,       -- pairs before filtering (audit of filter bite)
    config_version_id BIGINT NOT NULL REFERENCES config_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_ts ON watchlist_snapshots (ts DESC);

-- Unlock calendar (pluggable source; CSV stub loads here)
CREATE TABLE IF NOT EXISTS token_unlocks (
    id          BIGSERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    unlock_at   TIMESTAMPTZ NOT NULL,
    supply_pct  DOUBLE PRECISION NOT NULL,
    source      TEXT NOT NULL DEFAULT 'csv',
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, unlock_at, source)
);

-- ---------- ANALYST -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS proposals (
    id                 BIGSERIAL PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    pair               TEXT NOT NULL,
    setup_type         TEXT NOT NULL,     -- range | breakout_retest | rs_momentum
    side               TEXT NOT NULL DEFAULT 'long',
    entry_price        DOUBLE PRECISION NOT NULL,
    stop_price         DOUBLE PRECISION NOT NULL,
    targets            JSONB NOT NULL,    -- [{price, r_multiple}]
    evidence           JSONB NOT NULL,    -- FULL indicator snapshot: candles summary,
                                          -- range touches / breakout level + volume mult /
                                          -- RS decile + EMA + stochRSI, all values
    regime_snapshot_id BIGINT NOT NULL REFERENCES regime_snapshots(id),
    watchlist_id       BIGINT REFERENCES watchlist_snapshots(id),
    config_version_id  BIGINT NOT NULL REFERENCES config_versions(id)
);
CREATE INDEX IF NOT EXISTS idx_proposals_ts ON proposals (ts DESC);

-- Risk's verdict is a separate append-only row, not a status column.
CREATE TABLE IF NOT EXISTS proposal_decisions (
    id           BIGSERIAL PRIMARY KEY,
    proposal_id  BIGINT NOT NULL REFERENCES proposals(id),
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision     TEXT NOT NULL,           -- accepted | rejected
    reject_reasons JSONB,                 -- ["max_concurrent", "sector_cap:L1", ...]
    sizing       JSONB,                   -- accepted only: {qty, notional, risk_quote,
                                          --  risk_pct, equity_at_decision}
    UNIQUE (proposal_id)                  -- risk rules on a proposal exactly once
);

-- ---------- TRADES (event-sourced core) ---------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    trade_id          UUID PRIMARY KEY,
    proposal_id       BIGINT NOT NULL REFERENCES proposals(id),
    pair              TEXT NOT NULL,
    setup_type        TEXT NOT NULL,
    mode              TEXT NOT NULL,      -- paper | live | backtest
    opened_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    config_version_id BIGINT NOT NULL REFERENCES config_versions(id)
);

CREATE TABLE IF NOT EXISTS trade_events (
    id          BIGSERIAL PRIMARY KEY,
    trade_id    UUID NOT NULL REFERENCES trades(trade_id),
    seq         INT  NOT NULL,            -- per-trade ordering
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    type        TEXT NOT NULL,
    -- OPENED | PARTIAL_EXIT_TP1 | STOP_TO_BREAKEVEN | PARTIAL_EXIT_TP2 |
    -- TRAIL_MOVED | STOP_HIT | TRAIL_HIT | CLOSED | HALT_FLATTENED
    qty_delta   DOUBLE PRECISION NOT NULL DEFAULT 0,   -- signed; negative = exit
    price       DOUBLE PRECISION,
    fees_quote  DOUBLE PRECISION NOT NULL DEFAULT 0,   -- incl. modeled taker fee + slippage (paper)
    stop_after  DOUBLE PRECISION,        -- stop level in force after this event
    r_at_event  DOUBLE PRECISION,        -- R multiple at this price
    detail      JSONB,                   -- e.g. {slippage_bps, swing_low_ref, reason}
    UNIQUE (trade_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_trade_events_trade ON trade_events (trade_id, seq);

-- Order lifecycle (paper fills simulated; live fills from exchange), append-only.
CREATE TABLE IF NOT EXISTS order_events (
    id         BIGSERIAL PRIMARY KEY,
    trade_id   UUID REFERENCES trades(trade_id),
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode       TEXT NOT NULL,             -- paper | live
    exchange_order_id TEXT,               -- null in paper
    type       TEXT NOT NULL,             -- submitted | filled | partially_filled | canceled | rejected
    side       TEXT NOT NULL,
    qty        DOUBLE PRECISION,
    price      DOUBLE PRECISION,
    detail     JSONB
);

-- ---------- EQUITY / BREAKERS -------------------------------------------------
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id     BIGSERIAL PRIMARY KEY,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode   TEXT NOT NULL,                 -- paper | live
    equity DOUBLE PRECISION NOT NULL,     -- quote currency (USDT)
    detail JSONB                          -- {cash, positions_value}
);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots (mode, ts DESC);

-- Halts as events: imposed and cleared are both rows (append-only).
CREATE TABLE IF NOT EXISTS halt_events (
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    scope    TEXT NOT NULL,               -- daily | weekly | kill | manual
    action   TEXT NOT NULL,               -- imposed | cleared
    reason   TEXT NOT NULL,               -- weekly clear REQUIRES typed confirmation text here
    detail   JSONB                        -- {equity_drop_pct, trigger_snapshot_id, ...}
);

-- ---------- COACH -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coach_reports (
    id        BIGSERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    period    TEXT NOT NULL,              -- daily | weekly
    range_from TIMESTAMPTZ NOT NULL,
    range_to   TIMESTAMPTZ NOT NULL,
    metrics   JSONB NOT NULL,             -- {win_rate, avg_r, expectancy, profit_factor,
                                          --  max_drawdown, by_setup:{}, by_regime:{},
                                          --  by_pair:{}, rejected_review:[]}
    narrative TEXT NOT NULL               -- plain-English summary
);

-- ---------- read models (derived; safe to rebuild) ----------------------------
CREATE OR REPLACE VIEW v_trade_state AS
SELECT t.trade_id, t.pair, t.setup_type, t.mode, t.opened_at,
       SUM(e.qty_delta)                                   AS open_qty,
       MAX(e.ts)                                          AS last_event_at,
       BOOL_OR(e.type IN ('CLOSED','STOP_HIT','TRAIL_HIT','HALT_FLATTENED')
               AND e.seq = (SELECT MAX(seq) FROM trade_events x WHERE x.trade_id = t.trade_id))
                                                          AS is_closed,
       SUM(-e.qty_delta * e.price) FILTER (WHERE e.qty_delta < 0)
         - SUM(e.qty_delta * e.price) FILTER (WHERE e.qty_delta > 0)
         - SUM(e.fees_quote)                              AS realized_pnl_quote
FROM trades t JOIN trade_events e USING (trade_id)
GROUP BY t.trade_id;

CREATE OR REPLACE VIEW v_open_positions AS
SELECT * FROM v_trade_state WHERE NOT is_closed AND open_qty > 0;

-- The paper->live gate, queryable: code requires ready = true AND config
-- live:true AND the CLI confirmation flag. Three independent locks.
CREATE OR REPLACE VIEW v_paper_readiness AS
SELECT COUNT(DISTINCT date_trunc('day', opened_at))            AS paper_days,
       COUNT(*)                                                AS paper_trades,
       MIN(opened_at)                                          AS first_paper_trade,
       COUNT(DISTINCT date_trunc('day', opened_at)) >= 30      AS ready
FROM trades WHERE mode = 'paper';
