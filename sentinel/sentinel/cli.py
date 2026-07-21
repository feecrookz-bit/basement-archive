"""CLI entrypoint: python -m sentinel {run|backtest|report|resume}.

The --confirm-live-i-accept-losses flag is the second of three live-gate
locks. Without it, `mode.live: true` in config still runs paper.
`resume` clears a weekly halt and REQUIRES a typed reason (logged forever).
"""
import argparse
import asyncio
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="sentinel")
    sub = p.add_subparsers(dest="cmd", required=True)

    runp = sub.add_parser("run", help="start the engine (paper unless fully gated)")
    runp.add_argument("--confirm-live-i-accept-losses", action="store_true",
                      dest="confirm_live",
                      help="CLI lock for live mode. Also requires mode.live: true "
                           "in config AND >=30 logged paper days.")

    btp = sub.add_parser("backtest", help="replay klines through the live pipeline")
    btp.add_argument("--symbol", default="ALT/USDT")
    btp.add_argument("--fixtures", default=None,
                     help="path to a klines JSON file; omit to fetch from Binance")
    btp.add_argument("--days", type=int, default=30)

    rep = sub.add_parser("report", help="run a coach report now")
    rep.add_argument("--period", choices=["daily", "weekly"], default="daily")

    res = sub.add_parser("resume", help="clear a weekly halt (typed reason required)")
    res.add_argument("--reason", required=True,
                     help="why resuming is justified; stored in halt_events forever")

    args = p.parse_args(argv)

    if args.cmd == "run":
        from .workers import main as run_main
        asyncio.run(run_main(cli_confirmed_live=args.confirm_live))
    elif args.cmd == "backtest":
        from .backtest import main as bt_main
        asyncio.run(bt_main(args.symbol, args.fixtures, args.days))
    elif args.cmd == "report":
        async def _rep():
            from . import db
            from .ledger import PgLedger
            from .modules import coach
            pool = await db.init()
            await coach.run_report(pool, PgLedger(pool), args.period)
            await db.close()
        asyncio.run(_rep())
    elif args.cmd == "resume":
        if len(args.reason.strip()) < 10:
            print("resume reason too short — write the actual justification",
                  file=sys.stderr)
            sys.exit(2)

        async def _resume():
            from . import db
            from .ledger import PgLedger
            pool = await db.init()
            await PgLedger(pool).insert_halt("weekly", "cleared", args.reason.strip())
            await db.close()
            print("weekly halt cleared; reason logged")
        asyncio.run(_resume())


if __name__ == "__main__":
    main()
