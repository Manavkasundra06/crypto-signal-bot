"""
Sentiment Analysis — Fetches and scores crypto news from RSS feeds.

Uses feedparser and TextBlob to analyze sentiment locally.
Completely free, no API limits.

Rate limiting: max 1 request per SENTIMENT_RATE_LIMIT seconds.
Caching:      responses cached for SENTIMENT_CACHE_TTL seconds.
"""

import time
import logging
from typing import Any

import feedparser
from textblob import TextBlob

import config

logger = logging.getLogger(__name__)

# ── Module-level state ───────────────────────────────────────────────
_cache: dict[str, dict[str, Any]] = {}       # asset → cached response
_cache_ts: dict[str, float] = {}              # asset → cache timestamp
_last_request_ts: float = 0.0                 # global rate-limiter

# ── RSS Feeds ────────────────────────────────────────────────────────
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/.rss/full/"
]

class SentimentFetchError(Exception):
    """Raised when RSS feeds cannot be fetched successfully."""


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
    Extract base asset code, e.g., 'BTC' from 'BTC/USDT'.
    """
    return asset.split("/")[0].upper()


def fetch_sentiment(asset: str) -> dict:
    """
    Fetch news for *asset* via RSS and analyze sentiment locally.

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

    logger.info("Fetching RSS headlines for %s", code)
    results: list[dict] = []
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get('title', '')
                description = entry.get('summary', '')
                text_content = f"{title} {description}"

                # Only include news that mentions the asset
                if code.lower() in text_content.lower():
                    # Local NLP sentiment analysis via TextBlob
                    analysis = TextBlob(text_content)
                    polarity = analysis.sentiment.polarity
                    
                    if polarity > 0.1:
                        sentiment_label = "Bullish"
                        bullish_count += 1
                    elif polarity < -0.1:
                        sentiment_label = "Bearish"
                        bearish_count += 1
                    else:
                        sentiment_label = "Neutral"
                        neutral_count += 1
                        
                    results.append({
                        "title": title,
                        "sentiment": sentiment_label,
                        "published_at": entry.get('published', '')
                    })
        except Exception as exc:
            logger.error("Failed to parse RSS feed %s: %s", url, exc)
            continue
            
    if not results:
        # No news found for this asset
        score = 50.0
        label = "Neutral"
    else:
        # Score calculation: [0, 100] scale
        n = len(results)
        score = (( (bullish_count - bearish_count) / n ) + 1) / 2 * 100
        score = round(max(0.0, min(100.0, score)), 2)

        if score >= 60:
            label = "Bullish"
        elif score <= 40:
            label = "Bearish"
        else:
            label = "Neutral"

    output = {
        "score": score,
        "label": label,
        "headline_count": len(results),
        "headlines": results[:50],  # Keep up to top 50 recent
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
    }

    _cache[code] = output
    _cache_ts[code] = now

    logger.info(
        "Sentiment for %s: score=%.1f (%s), headlines=%d",
        code, score, label, len(results),
    )
    return output
