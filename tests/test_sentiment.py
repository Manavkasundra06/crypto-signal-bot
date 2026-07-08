"""Tests for sentiment.py — headline scoring and aggregation (AlphaVantage)."""

from unittest.mock import patch, MagicMock

from sentiment import (
    _map_alpha_sentiment,
    _aggregate_score,
    _extract_asset_code,
    fetch_sentiment,
)


class TestMapAlphaSentiment:
    def test_bullish_mappings(self):
        assert _map_alpha_sentiment("Bullish") == "Bullish"
        assert _map_alpha_sentiment("Somewhat-Bullish") == "Bullish"

    def test_bearish_mappings(self):
        assert _map_alpha_sentiment("Bearish") == "Bearish"
        assert _map_alpha_sentiment("Somewhat-Bearish") == "Bearish"

    def test_neutral_mappings(self):
        assert _map_alpha_sentiment("Neutral") == "Neutral"
        assert _map_alpha_sentiment("Unknown") == "Neutral"


class TestAggregateScore:
    def test_all_bullish(self):
        headlines = [{"sentiment": "Bullish"}] * 5
        score, label = _aggregate_score(headlines)
        assert score == 100.0
        assert label == "Bullish"

    def test_all_bearish(self):
        headlines = [{"sentiment": "Bearish"}] * 5
        score, label = _aggregate_score(headlines)
        assert score == 0.0
        assert label == "Bearish"

    def test_balanced(self):
        headlines = [
            {"sentiment": "Bullish"},
            {"sentiment": "Bearish"},
        ]
        score, label = _aggregate_score(headlines)
        assert score == 50.0
        assert label == "Neutral"


class TestExtractAssetCode:
    def test_standard_pair(self):
        assert _extract_asset_code("BTC/USDT") == "CRYPTO:BTC"
        assert _extract_asset_code("ETH/USDT") == "CRYPTO:ETH"


class TestFetchSentiment:
    @patch("sentiment.requests.get")
    @patch("sentiment._rate_limit")
    def test_parses_api_response(self, mock_rl, mock_get):
        """Ensure headlines are parsed and scored from a mocked API response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "feed": [
                {
                    "title": "BTC breaks ATH",
                    "overall_sentiment_label": "Somewhat-Bullish",
                    "ticker_sentiment": [
                        {"ticker": "CRYPTO:BTC", "ticker_sentiment_label": "Bullish"}
                    ],
                    "time_published": "2026-07-08T08:00:00Z",
                },
                {
                    "title": "Market crash incoming?",
                    "overall_sentiment_label": "Somewhat-Bearish",
                    "ticker_sentiment": [
                        {"ticker": "CRYPTO:BTC", "ticker_sentiment_label": "Bearish"}
                    ],
                    "time_published": "2026-07-08T07:00:00Z",
                },
                {
                    "title": "Regulatory update",
                    "overall_sentiment_label": "Neutral",
                    "ticker_sentiment": [
                        {"ticker": "CRYPTO:BTC", "ticker_sentiment_label": "Neutral"}
                    ],
                    "time_published": "2026-07-08T06:00:00Z",
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # Clear cache for fresh fetch
        import sentiment
        sentiment._cache.clear()
        sentiment._cache_ts.clear()

        result = fetch_sentiment("BTC/USDT")

        assert result["headline_count"] == 3
        assert result["bullish_count"] == 1
        assert result["bearish_count"] == 1
        assert result["neutral_count"] == 1
        assert result["label"] == "Neutral"
        assert 0 <= result["score"] <= 100
