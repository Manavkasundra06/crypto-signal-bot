"""Tests for notifier.py — message formatting and Telegram dispatch."""

from unittest.mock import patch, MagicMock

from signal_engine import Signal
from notifier import _format_alert, _escape_md, send_alert


class TestEscapeMd:
    def test_escapes_special_chars(self):
        assert _escape_md("BTC/USDT") == "BTC/USDT"  # / is not special in MD
        assert _escape_md("Score: 85.0") == "Score: 85\\.0"
        assert _escape_md("test_value") == "test\\_value"

    def test_plain_text_unchanged(self):
        assert _escape_md("hello world") == "hello world"


class TestFormatAlert:
    def test_contains_key_fields(self):
        sig = Signal(
            symbol="BTC/USDT",
            direction="BUY",
            confidence=0.785,
            entry_price=65432.10,
            stop_loss=64682.10,
            target=66932.10,
            technicals_breakdown={
                "rsi": 28.3,
                "rsi_score": 71.7,
                "volume_ratio": 1.4,
                "volume_score": 70.0,
                "composite_score": 71.0,
                "bias": "BULLISH",
            },
            sentiment_breakdown={
                "score": 77.5,
                "label": "Bullish",
                "headline_count": 12,
                "bullish_count": 8,
                "bearish_count": 2,
                "neutral_count": 2,
            },
            timestamp="2026-07-08 08:48:00 UTC",
        )
        msg = _format_alert(sig)
        assert "SIGNAL ALERT" in msg
        assert "BUY" in msg
        assert "78\\.5" in msg  # confidence % escaped
        assert "SIGNAL ONLY" in msg
        assert "65432" in msg  # entry price
        assert "Stop Loss" in msg
        assert "Target" in msg
        assert "BTC" in msg   # currency name


class TestSendAlert:
    @patch("notifier.requests.post")
    def test_sends_to_telegram(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        sig = Signal(
            symbol="TEST/USDT",
            direction="BUY",
            confidence=0.80,
            technicals_breakdown={"rsi": 30, "rsi_score": 70, "volume_ratio": 1.2,
                                  "volume_score": 60, "composite_score": 66, "bias": "BULLISH"},
            sentiment_breakdown={"score": 75, "label": "Bullish", "headline_count": 5,
                                 "bullish_count": 3, "bearish_count": 1, "neutral_count": 1},
        )

        # Clear cooldown state
        import notifier
        notifier._last_notify_time.clear()

        with patch("notifier.config") as mock_cfg:
            mock_cfg.TELEGRAM_BOT_TOKEN = "fake-token"
            mock_cfg.TELEGRAM_CHAT_ID = "12345"
            mock_cfg.TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
            mock_cfg.COOLDOWN_SECONDS = 900
            mock_cfg.TECHNICAL_WEIGHT = 0.6
            mock_cfg.SENTIMENT_WEIGHT = 0.4

            result = send_alert(sig)

        assert result is True
        mock_post.assert_called_once()

    def test_dry_run_does_not_send(self):
        sig = Signal(
            symbol="DRY/USDT",
            direction="SELL",
            confidence=0.75,
            technicals_breakdown={"rsi": 75, "rsi_score": 25, "volume_ratio": 0.8,
                                  "volume_score": 40, "composite_score": 31, "bias": "BEARISH"},
            sentiment_breakdown={"score": 20, "label": "Bearish", "headline_count": 3,
                                 "bullish_count": 0, "bearish_count": 2, "neutral_count": 1},
        )

        import notifier
        notifier._last_notify_time.clear()

        result = send_alert(sig, dry_run=True)
        assert result is True  # logged but not sent
