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
POSITION_SIZE_USD: float = float(os.getenv("POSITION_SIZE_USD", "100.0"))  # USD to spend per trade

# ── Technical Analysis ───────────────────────────────────────────────
RSI_PERIOD: int = 14
RSI_WEIGHT: float = 0.6          # within the technicals composite
VOLUME_WEIGHT: float = 0.4       # within the technicals composite
VOLUME_SMA_PERIOD: int = 20
VOLUME_GATE_RATIO: float = float(os.getenv("VOLUME_GATE_RATIO", "0.8"))  # min vol ratio to allow signal

# ── Sentiment (AlphaVantage) ─────────────────────────────────────────
ALPHAVANTAGE_API_KEY: str = os.getenv("ALPHAVANTAGE_API_KEY", "")
ALPHAVANTAGE_BASE_URL: str = "https://www.alphavantage.co/query"
SENTIMENT_CACHE_TTL: int = 10800   # seconds (3 hours) to protect 25/day free limit
SENTIMENT_RATE_LIMIT: float = 2.0  # min seconds between requests

# ── Decision Engine ──────────────────────────────────────────────────
TECHNICAL_WEIGHT: float = float(os.getenv("TECHNICAL_WEIGHT", "0.8"))
SENTIMENT_WEIGHT: float = float(os.getenv("SENTIMENT_WEIGHT", "0.2"))
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.70"))
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "900"))  # 15 min
MAX_CONCURRENT_TRADES: int = int(os.getenv("MAX_CONCURRENT_TRADES", "3"))  # max open trades at once

# ── Price Targets ────────────────────────────────────────────────────
ATR_PERIOD: int = 14                                               # for stop-loss calc
STOP_LOSS_ATR_MULTIPLIER: float = float(os.getenv("SL_ATR_MULT", "1.5"))
RISK_REWARD_RATIO: float = float(os.getenv("RISK_REWARD", "2.0"))  # target = RR × risk

# ── Trailing Stop Loss ────────────────────────────────────────────────
TRAILING_STOP_ENABLED: bool = os.getenv("TRAILING_STOP_ENABLED", "true").lower() == "true"
TRAILING_STOP_ACTIVATION_PCT: float = float(os.getenv("TRAILING_STOP_ACTIVATION_PCT", "0.5"))  # activate at 50% to target
TRAILING_STOP_DISTANCE_ATR: float = float(os.getenv("TRAILING_STOP_DISTANCE_ATR", "1.0"))       # trail by 1× ATR

# ── Telegram Notifications ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"

# ── Orchestrator ─────────────────────────────────────────────────────
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "60"))  # seconds
HEARTBEAT_INTERVAL_HOURS: int = int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "6"))  # send alive ping every N hours

# ── Trade Tracker ────────────────────────────────────────────────────
TRADE_UPDATE_INTERVAL: int = int(os.getenv("TRADE_UPDATE_INTERVAL", "300"))   # 5 min between updates
MAX_TRADE_DURATION: int = int(os.getenv("MAX_TRADE_DURATION", "86400"))       # 24h auto-expire
DAILY_REPORT_HOUR: int = int(os.getenv("DAILY_REPORT_HOUR", "18"))            # UTC hour to send report (18 = 11:30pm IST)

# ── Retry / Resilience ───────────────────────────────────────────────
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 2.0  # exponential backoff multiplier
