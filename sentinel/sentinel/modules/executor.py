"""EXECUTOR — order placement (paper default) + mechanical exit ladder.

The live gate has THREE independent locks, all enforced here in code:
  1. config `mode.live: true`
  2. the CLI flag --confirm-live-i-accept-losses at startup
  3. >= mode.min_paper_days distinct days of logged paper trades (from the
     ledger itself — v_paper_readiness — so it cannot be faked by config)
Anything less runs paper. There are no discretionary exits: the ladder is
sell 50% at 1.5R -> stop to breakeven -> sell 25% at 2.5R -> trail the
remainder on the 1h swing low. No martingale, no averaging down — adding to
an existing pair is rejected upstream by risk and not implemented here.
"""
import logging
from dataclasses import dataclass

from .. import indicators as ind
from .. import notify

log = logging.getLogger("executor")


# ---------------------------------------------------------------- live gate
def resolve_mode(cfg, cli_confirmed: bool, paper_days: int) -> str:
    """'live' only when all three locks are open; 'paper' otherwise."""
    want_live = bool(cfg.get("mode.live", False))
    enough_history = paper_days >= int(cfg.get("mode.min_paper_days", 30))
    if want_live and cli_confirmed and enough_history:
        return "live"
    if want_live and not cli_confirmed:
        log.warning("live requested but CLI confirmation flag missing -> paper")
    if want_live and not enough_history:
        log.warning("live requested but only %d paper days logged -> paper", paper_days)
    return "paper"


async def paper_days(pool) -> int:
    async with pool.acquire() as con:
        return await con.fetchval("SELECT paper_days FROM v_paper_readiness") or 0


# ---------------------------------------------------------------- fills
def paper_fill(side: str, ref_price: float, spread_pct: float | None,
               notional: float, cfg) -> dict:
    """Simulated fill: half-spread + size-scaled impact, plus taker fee."""
    half_spread = (spread_pct or 0.05) / 2 / 100
    base_bps = cfg.get("fees_and_fills.slippage.base_impact_bps", 5)
    per_10k = cfg.get("fees_and_fills.slippage.impact_per_10k_usd_bps", 1)
    impact = (base_bps + per_10k * notional / 10_000) / 10_000
    slip = half_spread + impact
    price = ref_price * (1 + slip) if side == "buy" else ref_price * (1 - slip)
    fee = notional * cfg.get("fees_and_fills.taker_fee_pct", 0.10) / 100
    return {"price": price, "fees_quote": round(fee, 6),
            "slippage_bps": round(slip * 10_000, 2)}


# ---------------------------------------------------------------- trade state machine
@dataclass
class TradeState:
    trade_id: str
    pair: str
    entry: float
    stop: float
    qty: float          # remaining quantity
    initial_qty: float
    tp1_done: bool = False
    tp2_done: bool = False

    def r(self, price: float) -> float:
        return (price - self.entry) / (self.entry - self.stop_initial) \
            if (self.entry - self.stop_initial) else 0.0

    @property
    def stop_initial(self) -> float:
        return self._stop_initial

    def __post_init__(self):
        self._stop_initial = self.stop


def step_trade(state: TradeState, price: float, candles_1h: list[dict], cfg) -> list[dict]:
    """Mechanical ladder: returns ordered actions for this price update.
    Pure — no I/O — so it is exhaustively testable and identical in
    paper/live/backtest."""
    actions: list[dict] = []
    if state.qty <= 0:
        return actions
    r_now = state.r(price)
    ladder = cfg.get("executor.exit_ladder", [
        {"at_r": 1.5, "sell_pct": 50, "then": "move_stop_to_breakeven"},
        {"at_r": 2.5, "sell_pct": 25},
    ])

    # stop / trail hit first — a losing exit beats a ladder fill at same tick.
    # STOP_HIT = the original loss-taking stop; a stop at/above entry
    # (breakeven move or trail) exiting is TRAIL_HIT — protective, not a loss.
    if price <= state.stop:
        actions.append({"type": "STOP_HIT" if state.stop < state.entry else "TRAIL_HIT",
                        "sell_qty": state.qty, "price": price, "r": round(r_now, 3)})
        state.qty = 0
        return actions

    rung1, rung2 = ladder[0], ladder[1] if len(ladder) > 1 else None
    if not state.tp1_done and r_now >= rung1["at_r"]:
        sell = state.initial_qty * rung1["sell_pct"] / 100
        sell = min(sell, state.qty)
        state.qty -= sell
        state.tp1_done = True
        actions.append({"type": "PARTIAL_EXIT_TP1", "sell_qty": sell,
                        "price": price, "r": round(r_now, 3)})
        if rung1.get("then") == "move_stop_to_breakeven":
            state.stop = state.entry
            actions.append({"type": "STOP_TO_BREAKEVEN", "stop": state.entry})
    if rung2 and state.tp1_done and not state.tp2_done and r_now >= rung2["at_r"]:
        sell = state.initial_qty * rung2["sell_pct"] / 100
        sell = min(sell, state.qty)
        state.qty -= sell
        state.tp2_done = True
        actions.append({"type": "PARTIAL_EXIT_TP2", "sell_qty": sell,
                        "price": price, "r": round(r_now, 3)})

    # trail the remainder once TP1 is done
    if state.tp1_done and state.qty > 0:
        lookback = cfg.get("executor.trail_remainder.swing_lookback_candles", 10)
        sl = ind.swing_low(candles_1h, lookback)
        if sl and sl > state.stop:
            state.stop = sl
            actions.append({"type": "TRAIL_MOVED", "stop": sl})
    return actions


# ---------------------------------------------------------------- orchestration
class Executor:
    def __init__(self, ledger, bus, cfg, mode: str, live_client=None):
        self.ledger = ledger
        self.bus = bus
        self.cfg = cfg
        self.mode = mode
        self.live_client = live_client  # ccxt instance; None in paper/backtest
        self.open: dict[str, TradeState] = {}

    async def on_accepted(self, msg: dict) -> None:
        proposal, sizing = msg["proposal"], msg["sizing"]
        fill = paper_fill("buy", proposal["entry_price"],
                          (proposal.get("evidence") or {})
                          .get("watchlist_entry", {}).get("spread_pct"),
                          sizing["notional"], self.cfg)
        if self.mode == "live":
            fill = await self._live_buy(proposal, sizing) or fill
        tid = await self.ledger.open_trade(
            proposal["id"], proposal["pair"], proposal["setup_type"],
            self.mode, proposal.get("config_version_id"))
        st = TradeState(trade_id=tid, pair=proposal["pair"],
                        entry=fill["price"], stop=proposal["stop_price"],
                        qty=sizing["qty"], initial_qty=sizing["qty"])
        self.open[tid] = st
        await self.ledger.append_trade_event(
            tid, "OPENED", sizing["qty"], fill["price"], fill["fees_quote"],
            proposal["stop_price"], 0.0,
            {"mode": self.mode, "slippage_bps": fill.get("slippage_bps"),
             "sizing": sizing})
        await self.bus.publish("executor", "executor.opened",
                               {"trade_id": tid, "pair": proposal["pair"],
                                "mode": self.mode})
        mode_tag = "🔴 LIVE" if self.mode == "live" else f"🟡 {self.mode}"
        conv = proposal.get("conviction")
        agree = proposal.get("agreeing_setups") or [proposal.get("setup_type")]
        await notify.send(
            title=f"📈 OPEN {proposal['pair']} · {mode_tag}",
            body=(f"{'+'.join(agree)} | conviction {conv if conv is not None else '—'}\n"
                  f"entry {fill['price']:.6g} · stop {proposal['stop_price']:.6g} "
                  f"· risk {sizing.get('risk_pct', '?')}%"))

    async def on_price(self, pair: str, price: float, candles_1h: list[dict]) -> None:
        for st in [s for s in self.open.values() if s.pair == pair]:
            for act in step_trade(st, price, candles_1h, self.cfg):
                await self._apply(st, act)
            if st.qty <= 0:
                closed = self.open.pop(st.trade_id, None)
                if closed is not None:
                    await self.ledger.append_trade_event(
                        st.trade_id, "CLOSED", 0, price, 0, st.stop, st.r(price))

    async def flatten_all(self, reason: str, prices: dict[str, float]) -> None:
        for st in list(self.open.values()):
            price = prices.get(st.pair, st.entry)
            notional = st.qty * price
            fill = paper_fill("sell", price, None, notional, self.cfg)
            await self.ledger.append_trade_event(
                st.trade_id, "HALT_FLATTENED", -st.qty, fill["price"],
                fill["fees_quote"], st.stop, st.r(price), {"reason": reason})
            st.qty = 0
            self.open.pop(st.trade_id, None)

    async def _apply(self, st: TradeState, act: dict) -> None:
        t = act["type"]
        if t in ("PARTIAL_EXIT_TP1", "PARTIAL_EXIT_TP2", "STOP_HIT", "TRAIL_HIT"):
            notional = act["sell_qty"] * act["price"]
            fill = paper_fill("sell", act["price"], None, notional, self.cfg)
            if self.mode == "live":
                await self._live_sell(st, act["sell_qty"])
            await self.ledger.append_trade_event(
                st.trade_id, t, -act["sell_qty"], fill["price"],
                fill["fees_quote"], st.stop, act.get("r"))
            emoji = {"PARTIAL_EXIT_TP1": "🟢", "PARTIAL_EXIT_TP2": "🟢🟢",
                     "STOP_HIT": "🔴", "TRAIL_HIT": "🛡️"}[t]
            await notify.send(
                title=f"{emoji} {t.replace('_', ' ')} {st.pair}",
                body=(f"{act.get('r', 0):+.2f}R @ {fill['price']:.6g} · "
                      f"sold {act['sell_qty']:.6g} · "
                      f"{'flat' if st.qty <= 0 else f'{st.qty:.6g} remaining'}"))
        elif t in ("STOP_TO_BREAKEVEN", "TRAIL_MOVED"):
            await self.ledger.append_trade_event(
                st.trade_id, t, 0, None, 0, act["stop"], None)

    async def _live_buy(self, proposal, sizing):
        """Live path stub: requires the triple gate to have resolved 'live'.
        Uses ccxt market orders; deliberately minimal until paper proves out."""
        if self.live_client is None:
            log.error("live mode without exchange client; falling back to paper fill")
            return None
        order = await self.live_client.create_order(
            proposal["pair"], "market", "buy", sizing["qty"])
        price = float(order.get("average") or order.get("price") or 0)
        fee = sum(f.get("cost", 0) for f in order.get("fees") or [])
        return {"price": price, "fees_quote": fee, "slippage_bps": None}

    async def _live_sell(self, st: TradeState, qty: float):
        if self.live_client is None:
            return
        await self.live_client.create_order(st.pair, "market", "sell", qty)
