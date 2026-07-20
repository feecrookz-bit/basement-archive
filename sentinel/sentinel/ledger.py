"""Ledger persistence adapters.

Strategy, risk, and executor logic write through this interface. Production
uses PgLedger (append-only tables from schema.sql); the backtest harness and
infra-less tests use MemoryLedger. The *logic* code path is identical — only
the persistence adapter differs, which is what keeps backtest ≈ paper ≈ live.

Append-only discipline: this interface exposes no update or delete for
ledger records. State transitions are new events.
"""
import json
import uuid
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc)


class MemoryLedger:
    """In-memory ledger with the same call surface as PgLedger."""

    def __init__(self):
        self.regimes: list[dict] = []
        self.watchlists: list[dict] = []
        self.proposals: list[dict] = []
        self.decisions: list[dict] = []
        self.trades: list[dict] = []
        self.trade_events: list[dict] = []
        self.halts: list[dict] = []
        self.equity: list[dict] = []
        self.reports: list[dict] = []

    async def insert_regime(self, snap: dict) -> int:
        snap = {**snap, "id": len(self.regimes) + 1, "ts": snap.get("ts") or _now()}
        self.regimes.append(snap)
        return snap["id"]

    async def insert_watchlist(self, entries: list[dict], universe_size: int,
                               config_version_id: int | None) -> int:
        row = {"id": len(self.watchlists) + 1, "ts": _now(), "entries": entries,
               "universe_size": universe_size,
               "config_version_id": config_version_id}
        self.watchlists.append(row)
        return row["id"]

    async def insert_proposal(self, p: dict) -> int:
        p = {**p, "id": len(self.proposals) + 1, "ts": p.get("ts") or _now()}
        self.proposals.append(p)
        return p["id"]

    async def insert_decision(self, proposal_id: int, decision: str,
                              reject_reasons: list[str] | None,
                              sizing: dict | None) -> None:
        self.decisions.append({"proposal_id": proposal_id, "ts": _now(),
                               "decision": decision,
                               "reject_reasons": reject_reasons, "sizing": sizing})

    async def open_trade(self, proposal_id: int, pair: str, setup_type: str,
                         mode: str, config_version_id: int | None) -> str:
        tid = str(uuid.uuid4())
        self.trades.append({"trade_id": tid, "proposal_id": proposal_id,
                            "pair": pair, "setup_type": setup_type, "mode": mode,
                            "opened_at": _now(),
                            "config_version_id": config_version_id})
        return tid

    async def append_trade_event(self, trade_id: str, type_: str, qty_delta: float,
                                 price: float | None, fees_quote: float,
                                 stop_after: float | None, r_at_event: float | None,
                                 detail: dict | None = None) -> None:
        seq = 1 + sum(1 for e in self.trade_events if e["trade_id"] == trade_id)
        self.trade_events.append({"trade_id": trade_id, "seq": seq, "ts": _now(),
                                  "type": type_, "qty_delta": qty_delta,
                                  "price": price, "fees_quote": fees_quote,
                                  "stop_after": stop_after,
                                  "r_at_event": r_at_event, "detail": detail})

    async def insert_halt(self, scope: str, action: str, reason: str,
                          detail: dict | None = None) -> None:
        self.halts.append({"ts": _now(), "scope": scope, "action": action,
                           "reason": reason, "detail": detail})

    async def insert_equity(self, mode: str, equity: float,
                            detail: dict | None = None) -> None:
        self.equity.append({"ts": _now(), "mode": mode, "equity": equity,
                            "detail": detail})

    async def insert_report(self, period: str, range_from, range_to,
                            metrics: dict, narrative: str) -> None:
        self.reports.append({"ts": _now(), "period": period,
                             "range_from": range_from, "range_to": range_to,
                             "metrics": metrics, "narrative": narrative})


class PgLedger:
    """asyncpg-backed ledger; same surface as MemoryLedger."""

    def __init__(self, pool):
        self.pool = pool

    async def insert_regime(self, snap: dict) -> int:
        async with self.pool.acquire() as con:
            return await con.fetchval(
                """
                INSERT INTO regime_snapshots (btc_state, trading_allowed,
                    ema_structure, atr_percentile, realized_vol_24h,
                    btc_move_1h_pct, kill_flags, config_version_id)
                VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7::jsonb,$8) RETURNING id
                """,
                snap["btc_state"], snap["trading_allowed"],
                json.dumps(snap.get("ema_structure") or {}, default=str),
                snap.get("atr_percentile"), snap.get("realized_vol_24h"),
                snap.get("btc_move_1h_pct"),
                json.dumps(snap.get("kill_flags") or []),
                snap.get("config_version_id"),
            )

    async def insert_watchlist(self, entries, universe_size, config_version_id) -> int:
        async with self.pool.acquire() as con:
            return await con.fetchval(
                "INSERT INTO watchlist_snapshots (entries, universe_size, config_version_id) "
                "VALUES ($1::jsonb,$2,$3) RETURNING id",
                json.dumps(entries, default=str), universe_size, config_version_id,
            )

    async def insert_proposal(self, p: dict) -> int:
        async with self.pool.acquire() as con:
            return await con.fetchval(
                """
                INSERT INTO proposals (pair, setup_type, side, entry_price,
                    stop_price, targets, evidence, regime_snapshot_id,
                    watchlist_id, config_version_id)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10) RETURNING id
                """,
                p["pair"], p["setup_type"], p.get("side", "long"),
                p["entry_price"], p["stop_price"],
                json.dumps(p.get("targets") or [], default=str),
                json.dumps(p.get("evidence") or {}, default=str),
                p["regime_snapshot_id"], p.get("watchlist_id"),
                p.get("config_version_id"),
            )

    async def insert_decision(self, proposal_id, decision, reject_reasons, sizing) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO proposal_decisions (proposal_id, decision, reject_reasons, sizing) "
                "VALUES ($1,$2,$3::jsonb,$4::jsonb) ON CONFLICT (proposal_id) DO NOTHING",
                proposal_id, decision,
                json.dumps(reject_reasons or [], default=str),
                json.dumps(sizing, default=str) if sizing else None,
            )

    async def open_trade(self, proposal_id, pair, setup_type, mode,
                         config_version_id) -> str:
        tid = str(uuid.uuid4())
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO trades (trade_id, proposal_id, pair, setup_type, mode, "
                "config_version_id) VALUES ($1,$2,$3,$4,$5,$6)",
                tid, proposal_id, pair, setup_type, mode, config_version_id,
            )
        return tid

    async def append_trade_event(self, trade_id, type_, qty_delta, price,
                                 fees_quote, stop_after, r_at_event,
                                 detail=None) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO trade_events (trade_id, seq, type, qty_delta, price,
                    fees_quote, stop_after, r_at_event, detail)
                VALUES ($1,
                        COALESCE((SELECT MAX(seq) FROM trade_events WHERE trade_id=$1), 0) + 1,
                        $2,$3,$4,$5,$6,$7,$8::jsonb)
                """,
                trade_id, type_, qty_delta, price, fees_quote, stop_after,
                r_at_event, json.dumps(detail, default=str) if detail else None,
            )

    async def insert_halt(self, scope, action, reason, detail=None) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO halt_events (scope, action, reason, detail) "
                "VALUES ($1,$2,$3,$4::jsonb)",
                scope, action, reason,
                json.dumps(detail, default=str) if detail else None,
            )

    async def insert_equity(self, mode, equity, detail=None) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO equity_snapshots (mode, equity, detail) VALUES ($1,$2,$3::jsonb)",
                mode, equity, json.dumps(detail, default=str) if detail else None,
            )

    async def insert_report(self, period, range_from, range_to, metrics, narrative) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO coach_reports (period, range_from, range_to, metrics, narrative) "
                "VALUES ($1,$2,$3,$4::jsonb,$5)",
                period, range_from, range_to,
                json.dumps(metrics, default=str), narrative,
            )
