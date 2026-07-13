"""
Centralised configuration for the Crypto Signal Generator.

Loads secrets from a `.env` file and exposes every tuneable knob as a
module-level constant so that other modules need only `import config`.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Exchange / Market Data ───────────────────────────────────────────
EXCHANGE: str = os.getenv("EXCHANGE", "binance")
SYMBOLS: list[str] = os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT").split(",")
TIMEFRAME: str = os.getenv("TIMEFRAME", "5m")
CANDLE_LIMIT: int = int(os.getenv("CANDLE_LIMIT", "100"))

# ── Auto Trading ─────────────────────────────────────────────────────
AUTO_TRADE_ENABLED: bool = os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"
BINANCE_TESTNET_API_KEY: str = os.getenv("BINANCE_TESTNET_API_KEY", "")
BINANCE_TESTNET_SECRET: str = os.getenv("BINANCE_TESTNET_SECRET", "")
LEVERAGE: int = int(os.getenv("LEVERAGE", "100"))
POSITION_SIZE_USD: float = float(os.getenv("POSITION_SIZE_USD", "100.0"))  # Fallback notional

# ── Dynamic Position Sizing ──────────────────────────────────────────
# Instead of fixed $100, risk a % of your ACTUAL Binance balance per trade.
DYNAMIC_SIZING_ENABLED: bool = os.getenv("DYNAMIC_SIZING_ENABLED", "true").lower() == "true"
RISK_PER_TRADE_PCT: float = float(os.getenv("RISK_PER_TRADE_PCT", "10.0"))  # Risk 10% of free balance per trade

# ── Technical Analysis ───────────────────────────────────────────────
RSI_PERIOD: int = 14
RSI_WEIGHT: float = 0.6          # within the technicals composite
VOLUME_WEIGHT: float = 0.4       # within the technicals composite
VOLUME_SMA_PERIOD: int = 20
VOLUME_GATE_RATIO: float = float(os.getenv("VOLUME_GATE_RATIO", "0.8"))  # min vol ratio to allow signal

# ── Sentiment (RSS + TextBlob) ───────────────────────────────────────
SENTIMENT_CACHE_TTL: int = 900     # seconds (15 mins) to avoid spamming RSS feeds
SENTIMENT_RATE_LIMIT: float = 2.0  # min seconds between requests


# ── Decision Engine ──────────────────────────────────────────────────
TECHNICAL_WEIGHT: float = float(os.getenv("TECHNICAL_WEIGHT", "0.8"))
SENTIMENT_WEIGHT: float = float(os.getenv("SENTIMENT_WEIGHT", "0.2"))
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.65"))
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "900"))  # 15 min
MAX_CONCURRENT_TRADES: int = int(os.getenv("MAX_CONCURRENT_TRADES", "3"))  # 3 trades max ($3 total margin used)

# ── Risk Management ──────────────────────────────────────────────────
# Tighter logic for High-Leverage / Micro-Account defense
ATR_PERIOD: int = 14
STOP_LOSS_ATR_MULTIPLIER: float = float(os.getenv("STOP_LOSS_ATR_MULTIPLIER", "1.2"))
RISK_REWARD_RATIO: float = float(os.getenv("RISK_REWARD_RATIO", "2.0")) # Target is 2x the stop loss

# ── Daily Loss Circuit Breaker ───────────────────────────────────────
# Auto-lock the bot after X losses in a single UTC day. Prevents tilt/revenge trading.
MAX_DAILY_LOSSES: int = int(os.getenv("MAX_DAILY_LOSSES", "3"))

# ── Partial Take Profit ──────────────────────────────────────────────
# Close a portion of the position at the first target to lock in guaranteed profit.
PARTIAL_TP_ENABLED: bool = os.getenv("PARTIAL_TP_ENABLED", "true").lower() == "true"
PARTIAL_TP_CLOSE_PCT: float = float(os.getenv("PARTIAL_TP_CLOSE_PCT", "50.0"))  # Close 50% at first target
PARTIAL_TP_TRIGGER_PCT: float = float(os.getenv("PARTIAL_TP_TRIGGER_PCT", "70.0"))  # Trigger when 70% of way to target

# ── Trailing Stop Loss ────────────────────────────────────────────────
TRAILING_STOP_ENABLED: bool = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
TRAILING_STOP_ACTIVATION_PCT: float = float(os.getenv("TRAILING_STOP_ACTIVATION_PCT", "0.5"))  # activate at 50% to target
TRAILING_STOP_DISTANCE_ATR: float = float(os.getenv("TRAILING_STOP_DISTANCE_ATR", "0.2"))       # trail by 0.2× ATR (must be tighter than initial SL)

# ── Telegram Notifications ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"

# ── Orchestrator ─────────────────────────────────────────────────────
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "15"))  # seconds (faster for 100x max leverage!)
HEARTBEAT_INTERVAL_HOURS: int = int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "6"))  # send alive ping every N hours

# ── Signal Confirmation ──────────────────────────────────────────────
# Wait this many seconds after sending alert before executing trade.
# During this time, re-validate price to filter out fake-outs.
SIGNAL_CONFIRMATION_DELAY: int = int(os.getenv("SIGNAL_CONFIRMATION_DELAY", "50"))
# Max allowed price drift (%) from signal entry during confirmation.
# If price drifts MORE than this against the trade direction, cancel it.
ENTRY_PRICE_TOLERANCE_PCT: float = float(os.getenv("ENTRY_PRICE_TOLERANCE_PCT", "0.15"))

# ── Session Filters ──────────────────────────────────────────────────
# 0 = Monday, 6 = Sunday. If True, bot will not open NEW trades on Sat/Sun.
AVOID_WEEKENDS: bool = os.getenv("AVOID_WEEKENDS", "false").lower() == "true"
# Allowed UTC hours (e.g. 7 to 20 for London/NY). If empty, trades 24/7.
ALLOWED_TRADING_HOURS_UTC: list[int] = []

# ── Trade Tracker ────────────────────────────────────────────────────
TRADE_UPDATE_INTERVAL: int = int(os.getenv("TRADE_UPDATE_INTERVAL", "300"))   # 5 min between updates
MAX_TRADE_DURATION: int = int(os.getenv("MAX_TRADE_DURATION", "86400"))       # 24h auto-expire
DAILY_REPORT_HOUR: int = int(os.getenv("DAILY_REPORT_HOUR", "18"))            # UTC hour to send report (18 = 11:30pm IST)

# ── Retry / Resilience ───────────────────────────────────────────────
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 2.0  # exponential backoff multiplier


# ── Fibonacci Strategy ──────────────────────────────────────────────────────
FIB_LOOKBACK_PERIOD: int = int(os.getenv("FIB_LOOKBACK_PERIOD", "200"))
USE_FIB_TARGETS: bool = os.getenv("USE_FIB_TARGETS", "true").lower() == "true"


# ── Institutional Filters (VWAP & EMA20) ────────────────────────────────────
USE_VWAP_FILTER: bool = os.getenv("USE_VWAP_FILTER", "true").lower() == "true"
USE_EMA20_TRIGGER: bool = os.getenv("USE_EMA20_TRIGGER", "true").lower() == "true"


# ── Smart Money Concepts (SMC) ──────────────────────────────────────────────
USE_SMC_LOGIC: bool = os.getenv("USE_SMC_LOGIC", "true").lower() == "true"
SMC_WEIGHT: float = float(os.getenv("SMC_WEIGHT", "0.2"))


# ── Zombie Trade Fix (Testnet Resiliency) ───────────────────────────────
MAX_API_FAILURES: int = int(os.getenv("MAX_API_FAILURES", "5"))
DUST_NOTIONAL_THRESHOLD: float = float(os.getenv("DUST_NOTIONAL_THRESHOLD", "1.0"))
