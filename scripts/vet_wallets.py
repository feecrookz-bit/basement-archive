#!/usr/bin/env python3
"""
vet_wallets.py — on-chain vetting for candidate tracked wallets.

Copy-trading famous wallets is a trap: the leaderboard names are the most
watched and the most farmed. This script scores candidates on the metrics
that actually decide whether a wallet is *trackable and shadowable* by the
memecoin tracker — using only public Helius RPC + the Enhanced API, so it
costs nothing on the free tier.

It does NOT re-derive PnL (leaderboards already do, and PnL alone is the
metric most easily faked by outliers). It measures the things a follower
system cares about and leaderboards hide:

  * ALIVE       — has the wallet traded recently at all?
  * CADENCE     — trades/day over the window (too few = nothing to shadow;
                  absurdly many = a bot/MEV wallet you can't follow)
  * SHADOWABLE  — median gap between trades. Sub-minute medians mean the
                  position is gone before your alert fires. You want
                  minutes-to-hours, not seconds.
  * FLIP RATE   — share of trades that are sells within 120s of the prior
                  buy on the same mint; high = a scalper/bot, low = holds
                  with conviction you can actually mirror.

Usage:
  HELIUS_API_KEY=... python scripts/vet_wallets.py \
      LABEL:ADDRESS [LABEL:ADDRESS ...]
  HELIUS_API_KEY=... python scripts/vet_wallets.py --file candidates.txt

Output: a ranked table + a JSON blob you can paste into /api/wallets adds.
Nothing here trades or writes; it is pure research.
"""
import asyncio
import json
import os
import statistics
import sys
from datetime import datetime, timezone

import aiohttp

KEY = os.getenv("HELIUS_API_KEY", "")
RPC = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
ENH = f"https://api.helius.xyz/v0/transactions?api-key={KEY}"
WINDOW_SIGS = 200          # how many recent signatures to analyze
FLIP_SECONDS = 120         # buy->sell faster than this = a flip


async def _rpc(sess, method, params):
    async with sess.post(RPC, json={"jsonrpc": "2.0", "id": 1,
                                    "method": method, "params": params},
                         timeout=30) as r:
        return ((await r.json(content_type=None)) or {}).get("result")


async def vet(sess, label, addr):
    sigs = []
    for attempt in range(3):  # tolerate free-tier rate limiting
        sigs = await _rpc(sess, "getSignaturesForAddress",
                          [addr, {"limit": WINDOW_SIGS}]) or []
        if sigs:
            break
        await asyncio.sleep(1.5 * (attempt + 1))
    ok = [s for s in sigs if not s.get("err") and s.get("blockTime")]
    if not ok:
        return {"label": label, "addr": addr, "verdict": "DEAD/INVALID",
                "score": 0, "notes": "no recent valid txs"}
    times = sorted((s["blockTime"] for s in ok))
    now = datetime.now(timezone.utc).timestamp()
    span_seconds = times[-1] - times[0]
    # A full sample window compressed into minutes = a high-frequency bot,
    # regardless of PnL. Flag it explicitly — these top the leaderboards but
    # cannot be shadowed by any follower system.
    if len(ok) >= 50 and span_seconds < 3600:
        return {"label": label, "addr": addr, "verdict": "HFT_BOT", "score": 0,
                "sampled": len(ok),
                "notes": f"{len(ok)} txs in {span_seconds/60:.1f}m — un-shadowable"}
    span_days = max(span_seconds / 86400, 1e-6)
    last_age_h = (now - times[-1]) / 3600
    gaps = [b - a for a, b in zip(times, times[1:])]
    median_gap_min = (statistics.median(gaps) / 60) if gaps else 0
    trades_per_day = len(ok) / span_days

    # flip rate via the Enhanced API on the sampled signatures
    flips = swaps = 0
    last_buy_ts = {}
    for i in range(0, min(len(ok), 100), 100):
        batch = [s["signature"] for s in ok[i:i + 100]]
        try:
            async with sess.post(ENH, json={"transactions": batch},
                                 timeout=45) as r:
                txs = await r.json(content_type=None) if r.status == 200 else []
        except Exception:  # noqa: BLE001
            txs = []
        for t in sorted(txs or [], key=lambda x: x.get("timestamp", 0)):
            ev = (t.get("events") or {}).get("swap") or {}
            if not ev and (t.get("type") or "").upper() != "SWAP":
                continue
            swaps += 1
            ts = t.get("timestamp", 0)
            outs = [x.get("mint") for x in ev.get("tokenOutputs") or []]
            ins = [x.get("mint") for x in ev.get("tokenInputs") or []]
            for m in outs:
                last_buy_ts[m] = ts
            for m in ins:
                if m in last_buy_ts and 0 < ts - last_buy_ts[m] <= FLIP_SECONDS:
                    flips += 1
    flip_rate = (flips / swaps) if swaps else 0.0

    # ---- scoring (0-100): rewards shadowable, alive, sane-cadence wallets ----
    score = 100
    notes = []
    if last_age_h > 48:
        score -= 40; notes.append(f"quiet {last_age_h:.0f}h")
    elif last_age_h > 12:
        score -= 10
    if trades_per_day < 0.5:
        score -= 25; notes.append("too few trades to shadow")
    elif trades_per_day > 60:
        score -= 30; notes.append(f"bot-like {trades_per_day:.0f}/day")
    if median_gap_min < 2:
        score -= 30; notes.append(f"median hold {median_gap_min:.1f}m (un-shadowable)")
    elif median_gap_min < 10:
        score -= 10
    if flip_rate > 0.4:
        score -= 20; notes.append(f"flip rate {flip_rate:.0%}")
    score = max(0, score)
    verdict = ("TRACK" if score >= 65 else
               "MAYBE" if score >= 45 else "SKIP")
    return {"label": label, "addr": addr, "verdict": verdict, "score": score,
            "last_age_h": round(last_age_h, 1),
            "trades_per_day": round(trades_per_day, 1),
            "median_gap_min": round(median_gap_min, 1),
            "flip_rate": round(flip_rate, 2), "sampled": len(ok),
            "notes": "; ".join(notes) or "clean"}


async def main(cands):
    if not KEY:
        print("set HELIUS_API_KEY", file=sys.stderr); sys.exit(2)
    async with aiohttp.ClientSession(trust_env=True) as sess:
        results = []
        for label, addr in cands:
            results.append(await vet(sess, label, addr))
            await asyncio.sleep(1.2)  # stay under free-tier rps across wallets
    results.sort(key=lambda r: r["score"], reverse=True)
    print(f"\n{'label':<14}{'verdict':<8}{'score':>5}  {'age_h':>6}"
          f"{'t/day':>7}{'gap_m':>7}{'flip':>6}  notes")
    print("-" * 92)
    for r in results:
        print(f"{r['label']:<14}{r['verdict']:<8}{r.get('score',0):>5}  "
              f"{r.get('last_age_h','-'):>6}{r.get('trades_per_day','-'):>7}"
              f"{r.get('median_gap_min','-'):>7}{r.get('flip_rate','-'):>6}  "
              f"{r.get('notes','')}")
    keep = [r for r in results if r["verdict"] == "TRACK"]
    print("\nADD THESE (verdict=TRACK):")
    print(json.dumps([{"wallet": r["addr"], "label": r["label"]} for r in keep],
                     indent=2))


def _parse(args):
    cands = []
    if args and args[0] == "--file":
        for line in open(args[1]):
            line = line.strip()
            if line and ":" in line and not line.startswith("#"):
                lbl, addr = line.split(":", 1)
                cands.append((lbl.strip(), addr.strip()))
    else:
        for a in args:
            if ":" in a:
                lbl, addr = a.split(":", 1)
                cands.append((lbl, addr))
    return cands


if __name__ == "__main__":
    asyncio.run(main(_parse(sys.argv[1:])))
