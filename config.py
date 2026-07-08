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

# ── Technical Analysis ───────────────────────────────────────────────
RSI_PERIOD: int = 14
RSI_WEIGHT: float = 0.6          # within the technicals composite
VOLUME_WEIGHT: float = 0.4       # within the technicals composite
VOLUME_SMA_PERIOD: int = 20

# ── Sentiment (AlphaVantage) ─────────────────────────────────────────
ALPHAVANTAGE_API_KEY: str = os.getenv("ALPHAVANTAGE_API_KEY", "")
ALPHAVANTAGE_BASE_URL: str = "https://www.alphavantage.co/query"
SENTIMENT_CACHE_TTL: int = 300   # seconds (5 min)
SENTIMENT_RATE_LIMIT: float = 2.0  # min seconds between requests

# ── Decision Engine ──────────────────────────────────────────────────
TECHNICAL_WEIGHT: float = float(os.getenv("TECHNICAL_WEIGHT", "0.6"))
SENTIMENT_WEIGHT: float = float(os.getenv("SENTIMENT_WEIGHT", "0.4"))
CONFIDENCE_THRESHOLD: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.70"))
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "900"))  # 15 min

# ── Price Targets ────────────────────────────────────────────────────
ATR_PERIOD: int = 14                                               # for stop-loss calc
STOP_LOSS_ATR_MULTIPLIER: float = float(os.getenv("SL_ATR_MULT", "1.5"))
RISK_REWARD_RATIO: float = float(os.getenv("RISK_REWARD", "2.0"))  # target = RR × risk

# ── Telegram Notifications ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"

# ── Orchestrator ─────────────────────────────────────────────────────
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "60"))  # seconds

# ── Trade Tracker ────────────────────────────────────────────────────
TRADE_UPDATE_INTERVAL: int = int(os.getenv("TRADE_UPDATE_INTERVAL", "300"))   # 5 min between updates
MAX_TRADE_DURATION: int = int(os.getenv("MAX_TRADE_DURATION", "86400"))       # 24h auto-expire

# ── Retry / Resilience ───────────────────────────────────────────────
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 2.0  # exponential backoff multiplier
