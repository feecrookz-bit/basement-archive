"""Pure-logic tests for the wallet quality classifier (no DB/network).
Run: python scripts/test_wallet_quality.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import wallet_quality as wq  # noqa: E402


class _Cfg:
    WALLET_MAX_TRADES_PER_DAY = 60
    WALLET_MIN_HOLD_MIN = 3
    WALLET_ACCUMULATOR_MAX_TPD = 8
    WALLET_ACCUMULATOR_MIN_GAP_MIN = 60


def test():
    c = _Cfg()
    # HFT bot: absurd cadence -> bot
    assert wq.classify(1876, 0.4, 200, c) == wq.BOT
    # sub-floor median hold even at modest cadence -> bot
    assert wq.classify(30, 1.0, 120, c) == wq.BOT
    # accumulator: calm cadence, long holds
    assert wq.classify(4, 180, 60, c) == wq.ACCUMULATOR
    # normal: in between
    assert wq.classify(20, 15, 80, c) == wq.NORMAL
    # not enough data
    assert wq.classify(None, None, 2, c) == wq.UNKNOWN
    assert wq.classify(10, 10, 3, c) == wq.UNKNOWN
    # boundary: exactly at the cap is not yet a bot
    assert wq.classify(60, 5, 100, c) == wq.NORMAL
    assert wq.classify(60.1, 5, 100, c) == wq.BOT
    print("wallet_quality.classify OK (7 cases)")


if __name__ == "__main__":
    test()
