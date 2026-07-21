"""News watcher pure functions: classification + pair matching."""
from sentinel.data import news


def test_classify():
    assert news.classify("Binance Will Delist ABC, DEF on 2026-08-01") == "delisting"
    assert news.classify("Binance Will List Dogwifhat (WIF)") == "listing"
    assert news.classify("Introducing XYZ on Binance Launchpool!") == "launchpool"
    assert news.classify("New HODLer Airdrops: QQQ") == "hodler_airdrop"
    assert news.classify("Scheduled maintenance for wallet upgrades") == "other"
    assert news.classify("") == "other"


def test_mentioned_bases():
    bases = {"SOL", "SUI", "WIF"}
    assert news.mentioned_bases("Binance Will List Dogwifhat (WIF)", bases) == ["WIF"]
    assert news.mentioned_bases("Notice on SOL and SUI networks", bases) == ["SOL", "SUI"]
    assert news.mentioned_bases("Nothing about our coins", bases) == []
    # substring safety: SOLAYER must not match SOL
    assert news.mentioned_bases("Introducing SOLAYER on Launchpool", bases) == []
