"""Central config, all from environment. See .env.example."""
import os

def _f(name: str, default: str) -> float:
    return float(os.getenv(name, default))

# --- Postgres ---
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://tracker:tracker@localhost:5432/tracker"
)

# --- Discovery (DEX Screener) ---
DISCOVERY_MODE = os.getenv("DISCOVERY_MODE", "poll").strip().lower()   # poll | ws
DISCOVERY_POLL_SECONDS = int(os.getenv("DISCOVERY_POLL_SECONDS", "6"))
DISCOVERY_CHAINS = [
    c.strip().lower() for c in os.getenv("DISCOVERY_CHAINS", "solana").split(",") if c.strip()
]

# --- Wallets (Helius / Solana) ---
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
WALLET_MODE = os.getenv("WALLET_MODE", "ws").strip().lower()           # ws | webhook | off
HELIUS_WS_URL = os.getenv("HELIUS_WS_URL", "wss://atlas-mainnet.helius-rpc.com")
HELIUS_RPC_URL = os.getenv(
    "HELIUS_RPC_URL", "https://mainnet.helius-rpc.com"
)
# Public base URL for WALLET_MODE=webhook (free tier). Empty = auto-derive in
# GitHub Codespaces from CODESPACE_NAME; otherwise required for webhook mode.
WEBHOOK_PUBLIC_URL = os.getenv("WEBHOOK_PUBLIC_URL", "")

# --- Signal gates (the rug filter) ---
FRESH_HOURS = int(os.getenv("FRESH_HOURS", "24"))
MIN_LIQUIDITY_USD = _f("MIN_LIQUIDITY_USD", "15000")      # below this = untradeable/rug bait
MIN_VOLUME_H1_USD = _f("MIN_VOLUME_H1_USD", "5000")       # dead pools don't pump
MAX_FDV_USD = _f("MAX_FDV_USD", "5000000")                # already-mooned = no edge left
MAX_TOP10_PCT = _f("MAX_TOP10_PCT", "35")                 # top-10 holders own > this% = exit liquidity
REQUIRE_MINT_REVOKED = os.getenv("REQUIRE_MINT_REVOKED", "true").lower() in {"1","true","yes"}
MIN_BUY_SOL = _f("MIN_BUY_SOL", "0.5")                    # ignore dust buys
MIN_SIGNAL_SCORE = _f("MIN_SIGNAL_SCORE", "1.5")          # alert threshold

# --- Paper trading ledger ---
PAPER_ENABLED = os.getenv("PAPER_ENABLED", "true").lower() in {"1","true","yes"}
PAPER_STAKE_SOL = _f("PAPER_STAKE_SOL", "1.0")
PAPER_TP_PCT = _f("PAPER_TP_PCT", "80")                   # take profit +80%
PAPER_SL_PCT = _f("PAPER_SL_PCT", "40")                   # stop loss -40%
PAPER_TIMEOUT_HOURS = _f("PAPER_TIMEOUT_HOURS", "12")     # close at market after this
PAPER_CHECK_SECONDS = int(os.getenv("PAPER_CHECK_SECONDS", "60"))
ASSUMED_SLIPPAGE_PCT = _f("ASSUMED_SLIPPAGE_PCT", "6")    # round-trip cost assumption

# --- Alerts (optional) ---
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Browser-like headers required by DEX Screener's edge (rejects bare clients).
DEX_HEADERS = {
    "Origin": "https://dexscreener.com",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# --- Moonshot mode (low-MC accumulation signals) ---
MOONSHOT_ENABLED = os.getenv("MOONSHOT_ENABLED", "true").lower() in {"1", "true", "yes"}
MOONSHOT_MIN_FDV = _f("MOONSHOT_MIN_FDV", "50000")        # below = pre-liquidity lottery
MOONSHOT_MAX_FDV = _f("MOONSHOT_MAX_FDV", "1500000")      # above = 100x math stops working
MOONSHOT_MIN_LIQ_PCT_FDV = _f("MOONSHOT_MIN_LIQ_PCT_FDV", "8")  # liq must be >= this % of FDV
MOONSHOT_MIN_LIQ_USD = _f("MOONSHOT_MIN_LIQ_USD", "10000")
MOONSHOT_MAX_TOP10_PCT = _f("MOONSHOT_MAX_TOP10_PCT", "30")
MOONSHOT_FRESH_HOURS = int(os.getenv("MOONSHOT_FRESH_HOURS", "168"))  # 7d discovery window
MOONSHOT_MIN_BUY_SOL = _f("MOONSHOT_MIN_BUY_SOL", "0.25") # accumulation buys are smaller
MOONSHOT_MIN_BUY_EVENTS = int(os.getenv("MOONSHOT_MIN_BUY_EVENTS", "3"))  # buys over the window
MOONSHOT_ACCUM_WINDOW_HOURS = int(os.getenv("MOONSHOT_ACCUM_WINDOW_HOURS", "168"))
MOONSHOT_MIN_ACCUM_SPAN_HOURS = _f("MOONSHOT_MIN_ACCUM_SPAN_HOURS", "12")  # buys spread out, not one burst
# Moonshot paper exits: let winners run, cut the dead, measure peak multiple.
MOONSHOT_SL_PCT = _f("MOONSHOT_SL_PCT", "60")
MOONSHOT_TIMEOUT_HOURS = _f("MOONSHOT_TIMEOUT_HOURS", "720")   # 30 days

# --- Method-3 gates (momentum only; None data never gates) ---
M3_MIN_BUY_SELL_RATIO_H1 = _f("M3_MIN_BUY_SELL_RATIO_H1", "1.0")  # h1 buys/sells must exceed
M3_MIN_VOLUME_M5_USD = _f("M3_MIN_VOLUME_M5_USD", "1000")         # momentum is current, not historical
M3_REQUIRE_HOLDER_GROWTH = os.getenv("M3_REQUIRE_HOLDER_GROWTH", "false").lower() in {"1", "true", "yes"}
HOLDER_COUNT_MAX_PAGES = int(os.getenv("HOLDER_COUNT_MAX_PAGES", "5"))  # DAS pages of 1000; 0 = off

# --- Binance events (exit-liquidity flags, not price prediction) ---
BINANCE_ENABLED = os.getenv("BINANCE_ENABLED", "true").lower() in {"1", "true", "yes"}
BINANCE_POLL_SECONDS = int(os.getenv("BINANCE_POLL_SECONDS", "300"))
BINANCE_ALPHA_URL = os.getenv(
    "BINANCE_ALPHA_URL",
    "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list",
)
BINANCE_CMS_URL = os.getenv(
    "BINANCE_CMS_URL",
    "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
    "?catalogId=48&pageNo=1&pageSize=20",
)

# --- Rotation overlay (Method 6: BTC dominance macro tide) ---
ROTATION_ENABLED = os.getenv("ROTATION_ENABLED", "true").lower() in {"1", "true", "yes"}
ROTATION_POLL_SECONDS = int(os.getenv("ROTATION_POLL_SECONDS", "3600"))
ROTATION_SHIFT_PP = _f("ROTATION_SHIFT_PP", "0.5")  # 24h pp move that flips the regime
COINGECKO_GLOBAL_URL = os.getenv(
    "COINGECKO_GLOBAL_URL", "https://api.coingecko.com/api/v3/global"
)

# --- Pump.fun graduation watcher ---
PUMPFUN_ENABLED = os.getenv("PUMPFUN_ENABLED", "true").lower() in {"1", "true", "yes"}
PUMPPORTAL_WS_URL = os.getenv("PUMPPORTAL_WS_URL", "wss://pumpportal.fun/api/data")
GRAD_RECLAIM_WINDOW_HOURS = _f("GRAD_RECLAIM_WINDOW_HOURS", "24")  # stop watching after this
GRAD_MIN_DUMP_PCT = _f("GRAD_MIN_DUMP_PCT", "20")  # dump depth before a reclaim counts
GRAD_MONITOR_MAX = int(os.getenv("GRAD_MONITOR_MAX", "60"))  # price fetches per tick (rate-limit guard)
