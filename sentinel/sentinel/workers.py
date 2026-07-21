"""Worker supervisor: ingestion + the five modules wired over the bus.

Chain per cycle: REGIME tick (5m) -> SCOUT watchlist (15m) -> ANALYST scan
on regime.tick/scout.watchlist -> RISK judges each analyst.proposal ->
EXECUTOR acts on risk.accepted and re-prices open trades every minute.
COACH reports nightly + weekly. Everything is logged to the events table.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import aiohttp

from . import config as config_mod
from . import db, notify
from .bus import Bus
from .data.ingest import BinanceRest, backfill, derivatives_overlay, kline_stream
from .data.market import LiveMarket
from .ledger import PgLedger
from .modules import analyst, coach, conviction, expectancy, regime, risk
from .modules.executor import Executor, paper_days, resolve_mode

log = logging.getLogger("workers")


class Supervisor:
    def __init__(self, cfg, market, ledger, bus, pool, executor: Executor):
        self.cfg = cfg
        self.market = market
        self.ledger = ledger
        self.bus = bus
        self.pool = pool
        self.executor = executor
        self.latest_regime: dict | None = None
        self.latest_watchlist: dict | None = None
        self.halt_until: datetime | None = None
        self.start_equity_day: float | None = None
        self.start_equity_week: float | None = None
        self.equity: float = 10_000.0  # paper account baseline

    # ---- account state assembly for risk ----
    async def account_state(self) -> risk.AccountState:
        async with self.pool.acquire() as con:
            entries_24h = await con.fetchval(
                "SELECT COUNT(*) FROM trades WHERE opened_at > now() - interval '24 hours'")
            open_rows = await con.fetch(
                """
                SELECT t.pair, d.sizing FROM v_open_positions v
                JOIN trades t USING (trade_id)
                JOIN proposal_decisions d ON d.proposal_id = t.proposal_id
                """)
        positions = []
        for r in open_rows:
            sizing = r["sizing"] or {}
            if isinstance(sizing, str):
                import json
                sizing = json.loads(sizing)
            positions.append({"pair": r["pair"],
                              "sector": risk.sector_of(r["pair"], self.cfg),
                              "risk_quote": sizing.get("risk_quote", 0)})
        day0 = self.start_equity_day or self.equity
        week0 = self.start_equity_week or self.equity
        return risk.AccountState(
            equity=self.equity,
            open_positions=positions,
            entries_last_24h=entries_24h or 0,
            daily_pnl_pct=100 * (self.equity - day0) / day0 if day0 else 0,
            weekly_pnl_pct=100 * (self.equity - week0) / week0 if week0 else 0,
            halted=self.halt_until is not None
                   and datetime.now(timezone.utc) < self.halt_until,
            atr_percentile=(self.latest_regime or {}).get("atr_percentile"),
        )

    # ---- module loops ----
    async def regime_loop(self):
        interval = self.cfg.get("regime.refresh_minutes", 5) * 60
        while True:
            try:
                self.latest_regime = await regime.tick(
                    self.market, self.ledger, self.bus, self.cfg)
            except Exception as e:  # noqa: BLE001
                log.warning("regime tick failed: %s", e)
            await asyncio.sleep(interval)

    async def scout_loop(self):
        interval = self.cfg.get("scout.refresh_minutes", 15) * 60
        while True:
            try:
                self.latest_watchlist = await scout_build(self)
            except Exception as e:  # noqa: BLE001
                log.warning("scout failed: %s", e)
            await asyncio.sleep(interval)

    async def analyst_loop(self):
        # scan after each fresh watchlist; regime gate applied inside
        while True:
            try:
                if self.latest_regime and self.latest_watchlist:
                    proposals = await analyst.scan(
                        self.market, self.ledger, self.bus, self.cfg,
                        self.latest_regime, self.latest_watchlist)
                    exp = await expectancy.setup_expectancy(self.ledger, self.cfg)
                    proposals = conviction.rank(proposals, exp, self.cfg)
                    state = await self.account_state()
                    for p in proposals:
                        verdict = await risk.judge(p, state, self.ledger,
                                                   self.bus, self.cfg)
                        if verdict["decision"] == "accepted":
                            await self.executor.on_accepted(
                                {"proposal": p, "sizing": verdict["sizing"]})
                            state = await self.account_state()  # refresh caps
            except Exception as e:  # noqa: BLE001
                log.warning("analyst/risk cycle failed: %s", e)
            await asyncio.sleep(60)

    async def price_loop(self):
        while True:
            try:
                state = await self.account_state()
                halt = risk.breaker_check(state, self.cfg)
                if halt and self.halt_until is None:
                    prices = {}
                    for st in self.executor.open.values():
                        prices[st.pair] = await self.market.last_price(st.pair) \
                            or st.entry
                    await self.executor.flatten_all(halt["reason"], prices)
                    hours = self.cfg.get("risk.circuit_breakers.daily_halt_hours", 24)
                    self.halt_until = datetime.now(timezone.utc) + timedelta(hours=hours)
                    await self.ledger.insert_halt(halt["scope"], "imposed",
                                                  halt["reason"])
                    await notify.send(
                        title=f"⛔ {halt['scope'].upper()} CIRCUIT BREAKER",
                        body=f"{halt['reason']}\nAll positions flattened.")
                if self.halt_until and datetime.now(timezone.utc) >= self.halt_until:
                    if (await self.account_state()).weekly_pnl_pct > \
                            -self.cfg.get("risk.circuit_breakers.weekly_loss_pct", 5.0):
                        self.halt_until = None  # daily halts auto-clear; weekly needs CLI
                for st in list(self.executor.open.values()):
                    price = await self.market.last_price(st.pair)
                    if price is None:
                        continue
                    candles = await self.market.candles(st.pair, "1h", 24)
                    await self.executor.on_price(st.pair, price, candles)
                await self.ledger.insert_equity(self.executor.mode, self.equity)
            except Exception as e:  # noqa: BLE001
                log.warning("price loop failed: %s", e)
            await asyncio.sleep(60)

    async def news_loop(self, session):
        """Binance announcement monitoring — data + alerts, never a signal."""
        from .data import news
        if not self.cfg.get("news.enabled", True):
            return
        interval = self.cfg.get("news.poll_minutes", 30) * 60
        seen: set[str] = set()
        first = True
        while True:
            try:
                bases = {p["pair"].split("/")[0].upper()
                         for p in (await self.account_state()).open_positions}
                for e in ((self.latest_watchlist or {}).get("entries") or []):
                    bases.add(e["pair"].split("/")[0].upper())
                if first:
                    # baseline pass: mark the current page as seen without
                    # alerting on stale articles from before startup
                    for a in await news.fetch_articles(session):
                        seen.add(str(a.get("code") or (a.get("title") or "")[:60]))
                    first = False
                else:
                    await news.check(session, self.bus, bases, seen, notify.send)
            except Exception as e:  # noqa: BLE001
                log.warning("news loop failed: %s", e)
            await asyncio.sleep(interval)

    async def coach_loop(self):
        last_daily = last_weekly = None
        gate_notified = False
        while True:
            now = datetime.now(timezone.utc)
            try:
                if not gate_notified:
                    async with self.pool.acquire() as con:
                        ready = await con.fetchval(
                            "SELECT ready FROM v_paper_readiness")
                    if ready:
                        gate_notified = True
                        await notify.send(
                            title="🔓 Paper→live gate is OPEN",
                            body=("30+ distinct paper-trade days logged. Live "
                                  "still requires mode.live: true AND the CLI "
                                  "confirmation flag — read the Coach's weekly "
                                  "setup breakdown before deciding."))
                if now.strftime("%H:%M") >= self.cfg.get("coach.daily_report_utc", "00:10") \
                        and last_daily != now.date():
                    await coach.run_report(self.pool, self.ledger, "daily")
                    last_daily = now.date()
                if now.strftime("%A").lower() == \
                        self.cfg.get("coach.weekly_report.day", "monday") \
                        and last_weekly != now.isocalendar()[1]:
                    await coach.run_report(self.pool, self.ledger, "weekly")
                    last_weekly = now.isocalendar()[1]
            except Exception as e:  # noqa: BLE001
                log.warning("coach failed: %s", e)
            await asyncio.sleep(300)


async def scout_build(sup: Supervisor):
    from .modules import scout as scout_mod
    return await scout_mod.build_watchlist(sup.market, sup.ledger, sup.bus, sup.cfg)


async def main(cli_confirmed_live: bool = False):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = config_mod.load()
    pool = await db.init()
    await config_mod.snapshot(pool, cfg)
    bus = await Bus.connect(pool=pool)

    import redis.asyncio as aioredis
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                          decode_responses=True)
    sess = aiohttp.ClientSession()
    rest = BinanceRest(sess)
    market = LiveMarket(r, rest)

    days = await paper_days(pool)
    mode = resolve_mode(cfg, cli_confirmed_live, days)
    live_client = None
    if mode == "live":
        import ccxt.async_support as ccxt
        live_client = ccxt.binance({
            "apiKey": os.getenv("BINANCE_API_KEY"),
            "secret": os.getenv("BINANCE_API_SECRET"),
        })
    log.warning("=== SENTINEL starting in %s MODE (paper days logged: %d) ===",
                mode.upper(), days)

    ledger = PgLedger(pool)
    executor = Executor(ledger, bus, cfg, mode, live_client)
    sup = Supervisor(cfg, market, ledger, bus, pool, executor)
    sup.start_equity_day = sup.start_equity_week = sup.equity

    # seed market data before the first regime tick
    symbols = ["BTC/USDT"]
    await backfill(r, rest, symbols)

    tasks = [
        asyncio.create_task(sup.regime_loop()),
        asyncio.create_task(sup.scout_loop()),
        asyncio.create_task(sup.analyst_loop()),
        asyncio.create_task(sup.price_loop()),
        asyncio.create_task(sup.coach_loop()),
        asyncio.create_task(sup.news_loop(sess)),
        asyncio.create_task(kline_stream(r, symbols, tfs=("15m", "1h"))),
        asyncio.create_task(derivatives_overlay(r, rest, symbols)),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        await sess.close()
        await db.close()
