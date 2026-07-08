"""
Sentiment Analysis — Fetches and scores crypto news from AlphaVantage.

Uses the AlphaVantage NEWS_SENTIMENT API to fetch recent headlines for
the requested asset, then maps AlphaVantage's NLP sentiment labels to
our Bullish/Bearish/Neutral system.

Rate limiting: max 1 request per SENTIMENT_RATE_LIMIT seconds.
Caching:      responses cached for SENTIMENT_CACHE_TTL seconds.
"""

import time
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# ── Module-level state ───────────────────────────────────────────────
_cache: dict[str, dict[str, Any]] = {}       # asset → cached response
_cache_ts: dict[str, float] = {}              # asset → cache timestamp
_last_request_ts: float = 0.0                 # global rate-limiter


class SentimentFetchError(Exception):
    """Raised when the AlphaVantage API cannot be reached."""


def _rate_limit() -> None:
    """Block until the minimum inter-request interval has elapsed."""
    global _last_request_ts
    elapsed = time.time() - _last_request_ts
    remaining = config.SENTIMENT_RATE_LIMIT - elapsed
    if remaining > 0:
        logger.debug("Sentiment rate limit: sleeping %.1fs", remaining)
        time.sleep(remaining)
    _last_request_ts = time.time()


def _extract_asset_code(asset: str) -> str:
    """
    Turn a trading pair like 'BTC/USDT' into an AlphaVantage ticker like 'CRYPTO:BTC'.
    """
    base = asset.split("/")[0].upper()
    return f"CRYPTO:{base}"


def _map_alpha_sentiment(label: str) -> str:
    """
    Map AlphaVantage sentiment labels to our internal labels.
    AlphaVantage labels: Bullish, Somewhat-Bullish, Neutral, Somewhat-Bearish, Bearish
    """
    label = label.lower()
    if "bullish" in label:
        return "Bullish"
    elif "bearish" in label:
        return "Bearish"
    return "Neutral"


def _aggregate_score(headlines: list[dict]) -> tuple[float, str]:
    """
    Aggregate individual headline sentiments into a single 0–100 score.
    """
    if not headlines:
        return 50.0, "Neutral"

    total = 0
    for h in headlines:
        if h["sentiment"] == "Bullish":
            total += 1
        elif h["sentiment"] == "Bearish":
            total -= 1

    # Normalise [-n, +n] → [0, 100]
    n = len(headlines)
    score = ((total / n) + 1) / 2 * 100
    score = round(max(0.0, min(100.0, score)), 2)

    if score >= 60:
        label = "Bullish"
    elif score <= 40:
        label = "Bearish"
    else:
        label = "Neutral"

    return score, label


def fetch_sentiment(asset: str) -> dict:
    """
    Fetch news headlines for *asset* and return aggregated sentiment.

    Parameters
    ----------
    asset : str   e.g. "BTC/USDT"

    Returns
    -------
    dict with full sentiment breakdown and headlines.
    """
    code = _extract_asset_code(asset)

    now = time.time()
    if code in _cache and (now - _cache_ts.get(code, 0)) < config.SENTIMENT_CACHE_TTL:
        logger.debug("Returning cached sentiment for %s", code)
        return _cache[code]

    _rate_limit()

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": code,
        "apikey": config.ALPHAVANTAGE_API_KEY,
        "limit": 50,  # AlphaVantage max per request
    }

    try:
        logger.info("Fetching AlphaVantage headlines for %s", code)
        resp = requests.get(
            config.ALPHAVANTAGE_BASE_URL,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        
        # Check for API-level rate limit message (AlphaVantage returns 200 OK with Information key)
        if "Information" in data and "rate limit" in data.get("Information", "").lower():
             logger.warning("AlphaVantage rate limit hit: %s", data.get("Information"))
             data = {"feed": []}
    except requests.RequestException as exc:
        raise SentimentFetchError(
            f"AlphaVantage API error for {code}: {exc}"
        ) from exc

    results: list[dict] = []
    
    feed = data.get("feed", [])
    for post in feed:
        # Try to find ticker-specific sentiment first
        sentiment_label = "Neutral"
        ticker_sentiment = post.get("ticker_sentiment", [])
        for ts in ticker_sentiment:
            if ts.get("ticker") == code:
                sentiment_label = ts.get("ticker_sentiment_label", "Neutral")
                break
        
        # Fallback to overall label if ticker specific isn't robust
        if sentiment_label == "Neutral":
             sentiment_label = post.get("overall_sentiment_label", "Neutral")
             
        mapped_sentiment = _map_alpha_sentiment(sentiment_label)
        
        results.append({
            "title": post.get("title", ""),
            "sentiment": mapped_sentiment,
            "published_at": post.get("time_published", ""),
        })

    score, label = _aggregate_score(results)

    bullish = sum(1 for h in results if h["sentiment"] == "Bullish")
    bearish = sum(1 for h in results if h["sentiment"] == "Bearish")
    neutral = sum(1 for h in results if h["sentiment"] == "Neutral")

    output = {
        "score": score,
        "label": label,
        "headline_count": len(results),
        "headlines": results,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
    }

    _cache[code] = output
    _cache_ts[code] = now

    logger.info(
        "Sentiment for %s: score=%.1f (%s), headlines=%d",
        code, score, label, len(results),
    )
    return output
