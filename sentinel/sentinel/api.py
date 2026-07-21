"""Read API for the dashboard. Read-heavy; the only write surface is
sign-in/sign-out — the engine still has no discretionary override buttons."""
import contextlib
import json

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from . import auth
from . import config as config_mod
from . import db


@contextlib.asynccontextmanager
async def lifespan(_app):
    await db.init()
    yield
    await db.close()


def require_session(request: Request) -> None:
    """401 unless auth is disabled or a valid session cookie is present."""
    if not auth.enabled():
        return
    if not auth.verify(request.cookies.get(auth.COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="sign in required")


app = FastAPI(title="Sentinel API", lifespan=lifespan)
# The dashboard proxies /api/* same-origin (next.config.js rewrites), so CORS
# only matters for direct-API setups. A wildcard origin is invalid for
# credentialed requests — echo the caller's origin instead.
app.add_middleware(CORSMiddleware, allow_origin_regex=".*",
                   allow_methods=["GET", "POST"], allow_headers=["*"],
                   allow_credentials=True)


@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {"enabled": auth.enabled(),
            "authenticated": (not auth.enabled())
            or auth.verify(request.cookies.get(auth.COOKIE_NAME))}


@app.post("/api/auth/login")
async def login(request: Request, response: Response):
    body = await request.json()
    if not auth.enabled():
        return {"ok": True, "note": "auth disabled"}
    if not auth.check_password(str(body.get("password") or "")):
        raise HTTPException(status_code=401, detail="wrong password")
    response.set_cookie(auth.COOKIE_NAME, auth.sign(), httponly=True,
                        samesite="lax", max_age=auth.DEFAULT_MAX_AGE, path="/")
    return {"ok": True}


@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


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


@app.get("/api/live", dependencies=[Depends(require_session)])
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
                     ORDER BY e.seq DESC LIMIT 1)  AS last_r,
                   t.setup_type, p.evidence
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
    # setup trust — what the ledger currently thinks of each setup
    setup_trust = {}
    cfg = None
    try:
        from .ledger import PgLedger
        from .modules import expectancy
        cfg = config_mod.load() if config_mod.DEFAULT_PATH.exists() else None
        if cfg:
            setup_trust = await expectancy.setup_expectancy(PgLedger(db.pool()), cfg)
    except Exception:  # noqa: BLE001
        setup_trust = {}

    # kill-zone clock + automated pre-session checklist (the mechanical
    # version of "5 signs you will lose today" — human factors excluded)
    killzone = None
    checklist = None
    try:
        from datetime import datetime, timezone
        from . import notify
        from .modules.ict import killzone as kz
        if cfg is None and config_mod.DEFAULT_PATH.exists():
            cfg = config_mod.load()
        if cfg:
            killzone = {**kz.state(datetime.now(timezone.utc), cfg),
                        "enabled": kz.enabled(cfg)}
        ict_rows = _rows(ict)
        first_ict = ict_rows[0] if ict_rows else {}
        sess = (first_ict.get("session_state") or {})
        lv = (first_ict.get("levels") or {})
        async with db.pool().acquire() as con:
            bad_news = await con.fetchval(
                "SELECT COUNT(*) FROM events WHERE type = 'news.announcement' "
                "AND payload::text LIKE '%delisting%' "
                "AND ts > now() - interval '24 hours'")
        checklist = {
            "bias_set": bool(regime and regime["btc_state"]),
            "asian_range_marked": (sess.get("asia") or {}).get("high") is not None,
            "key_levels_marked": lv.get("pdh") is not None,
            "news_clear": not bad_news,
            "alerts_ready": notify.configured(),
            "killzone_timing": bool(killzone and
                                    (killzone["active"] or not killzone["enabled"])),
        }
    except Exception:  # noqa: BLE001
        pass
    return {"regime": _rows([regime])[0] if regime else None,
            "watchlist": _rows([watchlist])[0] if watchlist else None,
            "open_positions": _rows(positions),
            "recent_halts": _rows(halts),
            "paper_readiness": dict(readiness) if readiness else None,
            "equity": dict(equity) if equity else None,
            "ict": _rows(ict),
            "setup_trust": setup_trust,
            "killzone": killzone,
            "checklist": checklist}


@app.get("/api/ledger", dependencies=[Depends(require_session)])
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


@app.get("/api/performance", dependencies=[Depends(require_session)])
async def performance():
    async with db.pool().acquire() as con:
        reports = await con.fetch(
            "SELECT * FROM coach_reports ORDER BY ts DESC LIMIT 30")
        equity = await con.fetch(
            "SELECT * FROM equity_snapshots ORDER BY ts ASC LIMIT 5000")
    return {"reports": _rows(reports), "equity_curve": _rows(equity)}


@app.get("/api/activity", dependencies=[Depends(require_session)])
async def activity(limit: int = 20):
    """Recent bus events — the in-app activity feed. The bus already archives
    everything to the events table; this is a typed read of the tail."""
    async with db.pool().acquire() as con:
        rows = await con.fetch(
            f"SELECT ts, module, type, payload FROM events "
            f"ORDER BY ts DESC LIMIT {min(limit, 100)}")
    out = []
    for r in _rows(rows):
        p = r.get("payload") or {}
        t = r["type"]
        if t == "regime.tick":
            summary = f"{p.get('btc_state')} · entries " + \
                      ("permitted" if p.get("trading_allowed") else "blocked")
        elif t == "scout.watchlist":
            summary = f"{len(p.get('entries') or [])} pairs ranked"
        elif t == "analyst.proposal":
            summary = f"{p.get('setup_type')} on {p.get('pair')}"
        elif t == "risk.accepted":
            pr = p.get("proposal") or {}
            summary = f"{pr.get('pair')} accepted " \
                      f"(risk {((p.get('sizing') or {}).get('risk_pct'))}%)"
        elif t == "risk.rejected":
            pr = p.get("proposal") or {}
            summary = f"{pr.get('pair')}: {', '.join(p.get('reasons') or [])}"
        elif t == "executor.opened":
            summary = f"{p.get('pair')} position opened ({p.get('mode')})"
        elif t == "decision.memo":
            summary = f"{p.get('status')}: {p.get('pair')} {p.get('setup_type')}"
        elif t == "news.announcement":
            summary = f"[{p.get('category')}] {(p.get('title') or '')[:70]}"
        else:
            summary = t
        out.append({"ts": r["ts"], "module": r["module"], "type": t,
                    "summary": summary})
    return out


@app.get("/api/memos", dependencies=[Depends(require_session)])
async def memos(limit: int = 30):
    """Decision memos — the final-verdict feed (APPROVED / WATCHLIST /
    REJECTED per proposal), read back from the persisted event bus."""
    async with db.pool().acquire() as con:
        rows = await con.fetch(
            f"SELECT ts, payload FROM events WHERE type = 'decision.memo' "
            f"ORDER BY ts DESC LIMIT {min(limit, 100)}")
    return [{"ts": r["ts"], **(r.get("payload") or {})} for r in _rows(rows)]


@app.get("/api/config", dependencies=[Depends(require_session)])
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
