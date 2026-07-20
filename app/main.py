"""FastAPI entrypoint. Launches the discovery + wallet workers on startup and
exposes a small read API, the Helius webhook receiver, and a dev dashboard."""
import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, discovery, paper, signals, wallets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

STATIC = Path(__file__).parent / "static"
_tasks: list[asyncio.Task] = []

@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.init()
    _tasks.append(asyncio.create_task(discovery.run(signals.on_discovery)))
    _tasks.append(asyncio.create_task(wallets.run(signals.on_wallet_hit)))
    _tasks.append(asyncio.create_task(paper.monitor()))
    log.info("workers started (discovery=%s, wallets=%s)",
             config.DISCOVERY_MODE, config.WALLET_MODE)
    try:
        yield
    finally:
        for t in _tasks:
            t.cancel()
        await asyncio.gather(*_tasks, return_exceptions=True)
        await db.close()

app = FastAPI(title="Memecoin Discovery + Wallet Tracker", lifespan=lifespan)

@app.get("/api/discovery")
async def api_discovery(chain: str | None = None, limit: int = 100):
    q = "SELECT * FROM tokens"
    args: list = []
    if chain:
        q += " WHERE chain_id = $1"
        args.append(chain.lower())
    q += f" ORDER BY first_seen DESC LIMIT {min(limit, 500)}"
    async with db.pool().acquire() as con:
        rows = await con.fetch(q, *args)
    return [dict(r) for r in rows]

@app.get("/api/signals")
async def api_signals(limit: int = 100):
    async with db.pool().acquire() as con:
        rows = await con.fetch(
            f"SELECT * FROM signals ORDER BY ts DESC LIMIT {min(limit, 500)}")
    return [dict(r) for r in rows]

@app.get("/api/wallets")
async def api_wallets():
    async with db.pool().acquire() as con:
        rows = await con.fetch("SELECT * FROM tracked_wallets ORDER BY added_at DESC")
    return [dict(r) for r in rows]

@app.post("/api/wallets")
async def add_wallet(req: Request):
    body = await req.json()
    wallet = (body.get("wallet") or "").strip()
    if not wallet:
        return JSONResponse({"error": "wallet required"}, status_code=400)
    async with db.pool().acquire() as con:
        await con.execute(
            "INSERT INTO tracked_wallets (wallet, label) VALUES ($1,$2) "
            "ON CONFLICT (wallet) DO UPDATE SET label = EXCLUDED.label",
            wallet, body.get("label"),
        )
    return {"ok": True, "wallet": wallet}

@app.delete("/api/wallets/{wallet}")
async def del_wallet(wallet: str):
    async with db.pool().acquire() as con:
        await con.execute("DELETE FROM tracked_wallets WHERE wallet=$1", wallet)
    return {"ok": True}

@app.get("/api/paper")
async def api_paper(limit: int = 100):
    async with db.pool().acquire() as con:
        rows = await con.fetch(
            f"SELECT * FROM paper_trades ORDER BY opened_at DESC LIMIT {min(limit, 500)}")
    return {"summary": await paper.ledger_summary(), "trades": [dict(r) for r in rows]}

@app.get("/api/checks/{token}")
async def api_check(token: str, force: bool = False):
    from . import enrich
    return await enrich.check_token(token, force=force)

@app.post("/webhooks/helius")
async def helius_webhook(req: Request):
    """Fallback ingestion for WALLET_MODE=webhook (Helius enhanced webhooks)."""
    payload = await req.json()
    await wallets.parse_webhook(payload, signals.on_wallet_hit)
    return {"ok": True}

@app.get("/")
async def dashboard():
    return FileResponse(STATIC / "index.html")

app.mount("/static", StaticFiles(directory=STATIC), name="static")
