"""Read API for the dashboard. Read-heavy, no write endpoints — the engine
has no discretionary override surface by design."""
import contextlib
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config as config_mod
from . import db


@contextlib.asynccontextmanager
async def lifespan(_app):
    await db.init()
    yield
    await db.close()

app = FastAPI(title="Sentinel API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
                   allow_headers=["*"])


def _rows(rows):
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, str) and v[:1] in "[{":
                try:
                    d[k] = json.loads(v)
                except ValueError:
                    pass
        out.append(d)
    return out


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/live")
async def live():
    async with db.pool().acquire() as con:
        regime = await con.fetchrow(
            "SELECT * FROM regime_snapshots ORDER BY ts DESC LIMIT 1")
        watchlist = await con.fetchrow(
            "SELECT * FROM watchlist_snapshots ORDER BY ts DESC LIMIT 1")
        positions = await con.fetch(
            """
            SELECT v.*, p.entry_price, p.stop_price, p.targets,
                   (SELECT stop_after FROM trade_events e
                     WHERE e.trade_id = v.trade_id AND e.stop_after IS NOT NULL
                     ORDER BY e.seq DESC LIMIT 1)  AS current_stop,
                   (SELECT r_at_event FROM trade_events e
                     WHERE e.trade_id = v.trade_id AND e.r_at_event IS NOT NULL
                     ORDER BY e.seq DESC LIMIT 1)  AS last_r
            FROM v_open_positions v
            JOIN trades t USING (trade_id)
            JOIN proposals p ON p.id = t.proposal_id
            """)
        halts = await con.fetch(
            "SELECT * FROM halt_events ORDER BY ts DESC LIMIT 5")
        readiness = await con.fetchrow("SELECT * FROM v_paper_readiness")
        equity = await con.fetchrow(
            "SELECT equity, mode, ts FROM equity_snapshots ORDER BY ts DESC LIMIT 1")
        ict = await con.fetch(
            """
            SELECT DISTINCT ON (pair) pair, ts, session_state, levels, zones
            FROM ict_snapshots
            WHERE ts > now() - interval '2 hours'
            ORDER BY pair, ts DESC
            """)
    return {"regime": _rows([regime])[0] if regime else None,
            "watchlist": _rows([watchlist])[0] if watchlist else None,
            "open_positions": _rows(positions),
            "recent_halts": _rows(halts),
            "paper_readiness": dict(readiness) if readiness else None,
            "equity": dict(equity) if equity else None,
            "ict": _rows(ict)}


@app.get("/api/ledger")
async def ledger(limit: int = 100):
    async with db.pool().acquire() as con:
        trades = await con.fetch(
            f"""
            SELECT t.*, ts.open_qty, ts.is_closed, ts.realized_pnl_quote,
                   p.setup_type AS proposal_setup, p.entry_price, p.stop_price,
                   p.targets, p.evidence,
                   d.decision, d.reject_reasons, d.sizing
            FROM trades t
            JOIN v_trade_state ts USING (trade_id)
            JOIN proposals p ON p.id = t.proposal_id
            LEFT JOIN proposal_decisions d ON d.proposal_id = p.id
            ORDER BY t.opened_at DESC LIMIT {min(limit, 500)}
            """)
        events = await con.fetch(
            f"SELECT * FROM trade_events ORDER BY ts DESC LIMIT {min(limit * 5, 2000)}")
        rejected = await con.fetch(
            f"""
            SELECT d.*, p.pair, p.setup_type FROM proposal_decisions d
            JOIN proposals p ON p.id = d.proposal_id
            WHERE d.decision = 'rejected'
            ORDER BY d.ts DESC LIMIT {min(limit, 500)}
            """)
    return {"trades": _rows(trades), "events": _rows(events),
            "rejected": _rows(rejected)}


@app.get("/api/performance")
async def performance():
    async with db.pool().acquire() as con:
        reports = await con.fetch(
            "SELECT * FROM coach_reports ORDER BY ts DESC LIMIT 30")
        equity = await con.fetch(
            "SELECT * FROM equity_snapshots ORDER BY ts ASC LIMIT 5000")
    return {"reports": _rows(reports), "equity_curve": _rows(equity)}


@app.get("/api/config")
async def config_view():
    async with db.pool().acquire() as con:
        versions = await con.fetch(
            "SELECT id, loaded_at, content_hash FROM config_versions "
            "ORDER BY loaded_at DESC LIMIT 20")
        current = await con.fetchrow(
            "SELECT * FROM config_versions ORDER BY loaded_at DESC LIMIT 1")
    cfg = config_mod.load() if config_mod.DEFAULT_PATH.exists() else None
    return {"versions": _rows(versions),
            "current": _rows([current])[0] if current else None,
            "mode": {"live": bool(cfg.get("mode.live")) if cfg else False}}
