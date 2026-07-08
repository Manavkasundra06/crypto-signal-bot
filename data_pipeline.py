"""
Data Pipeline — Fetches OHLCV candles from a crypto exchange via ccxt.

The exchange is instantiated in READ-ONLY mode (no API credentials).
Built-in rate limiting and exponential-backoff retries protect against
API bans and transient network errors.
"""

import time
import logging

import ccxt
import pandas as pd

import config

logger = logging.getLogger(__name__)


class DataFetchError(Exception):
    """Raised when OHLCV data cannot be fetched after all retries."""


def _create_exchange() -> ccxt.Exchange:
    """Instantiate the configured exchange in read-only mode."""
    exchange_class = getattr(ccxt, config.EXCHANGE, None)
    if exchange_class is None:
        raise ValueError(f"Exchange '{config.EXCHANGE}' is not supported by ccxt")

    exchange = exchange_class({
        "enableRateLimit": True,  # ccxt-managed throttling
    })
    # Safety: remove any write capabilities just in case
    exchange.apiKey = None
    exchange.secret = None
    return exchange


# Module-level singleton — reused across calls
_exchange: ccxt.Exchange | None = None


def _get_exchange() -> ccxt.Exchange:
    global _exchange
    if _exchange is None:
        _exchange = _create_exchange()
    return _exchange


def fetch_ohlcv(
    symbol: str,
    timeframe: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles and return a tidy DataFrame.

    Parameters
    ----------
    symbol : str       e.g. "BTC/USDT"
    timeframe : str    e.g. "5m", defaults to config.TIMEFRAME
    limit : int        number of candles, defaults to config.CANDLE_LIMIT

    Returns
    -------
    pd.DataFrame with columns:
        timestamp (datetime), open, high, low, close, volume

    Raises
    ------
    DataFetchError  after exhausting retries
    """
    timeframe = timeframe or config.TIMEFRAME
    limit = limit or config.CANDLE_LIMIT
    exchange = _get_exchange()

    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            logger.info(
                "Fetching %s %s candles for %s (attempt %d/%d)",
                limit, timeframe, symbol, attempt, config.MAX_RETRIES,
            )
            raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

            df = pd.DataFrame(
                raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.sort_values("timestamp").reset_index(drop=True)

            logger.info("Fetched %d candles for %s", len(df), symbol)
            return df

        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as exc:
            last_error = exc
            wait = config.RETRY_BACKOFF_BASE ** attempt
            logger.warning(
                "Transient error fetching %s: %s — retrying in %.1fs",
                symbol, exc, wait,
            )
            time.sleep(wait)

        except ccxt.BaseError as exc:
            # Non-transient exchange errors (bad symbol, etc.)
            raise DataFetchError(
                f"Non-retryable exchange error for {symbol}: {exc}"
            ) from exc

    raise DataFetchError(
        f"Failed to fetch {symbol} after {config.MAX_RETRIES} retries: {last_error}"
    )
