"""Tests for signal_engine.py — confidence calculation, thresholding, cooldown."""

import time
from unittest.mock import patch

from signal_engine import evaluate, reset_cooldown, Signal


def _tech(composite: float, bias: str = "BULLISH") -> dict:
    return {
        "rsi": 30.0,
        "rsi_score": composite,
        "volume_ratio": 1.5,
        "volume_score": composite,
        "composite_score": composite,
        "signal_bias": bias,
        "current_price": 50000.0,
        "atr": 500.0,
    }


def _sent(score: float, label: str = "Bullish") -> dict:
    return {
        "score": score,
        "label": label,
        "headline_count": 10,
        "bullish_count": 7,
        "bearish_count": 2,
        "neutral_count": 1,
    }


class TestEvaluate:
    def setup_method(self):
        reset_cooldown()

    def test_high_confidence_buy(self):
        """Both signals strongly bullish → should produce a BUY."""
        sig = evaluate("BTC/USDT", _tech(85.0), _sent(80.0))
        assert sig is not None
        assert sig.direction == "BUY"
        assert sig.confidence >= 0.70

    def test_high_confidence_sell(self):
        """Both signals strongly bearish → should produce a SELL."""
        sig = evaluate("BTC/USDT", _tech(15.0, "BEARISH"), _sent(10.0, "Bearish"))
        assert sig is not None
        assert sig.direction == "SELL"
        assert sig.confidence >= 0.70

    def test_below_threshold_returns_none(self):
        """Neutral scores → confidence < 70% → no signal."""
        sig = evaluate("BTC/USDT", _tech(50.0, "NEUTRAL"), _sent(50.0, "Neutral"))
        assert sig is None

    def test_cooldown_blocks_second_signal(self):
        """After a signal, same asset should be blocked for COOLDOWN_SECONDS."""
        sig1 = evaluate("ETH/USDT", _tech(90.0), _sent(85.0))
        assert sig1 is not None

        # Immediately try again
        sig2 = evaluate("ETH/USDT", _tech(90.0), _sent(85.0))
        assert sig2 is None  # blocked by cooldown

    def test_different_symbol_not_blocked(self):
        """Cooldown is per-asset; different symbol should still fire."""
        sig1 = evaluate("BTC/USDT", _tech(90.0), _sent(85.0))
        assert sig1 is not None

        sig2 = evaluate("SOL/USDT", _tech(90.0), _sent(85.0))
        assert sig2 is not None  # different symbol

    def test_reset_cooldown(self):
        evaluate("BTC/USDT", _tech(90.0), _sent(85.0))
        reset_cooldown("BTC/USDT")
        sig = evaluate("BTC/USDT", _tech(90.0), _sent(85.0))
        assert sig is not None

    def test_signal_dataclass(self):
        sig = evaluate("BTC/USDT", _tech(90.0), _sent(85.0))
        assert isinstance(sig, Signal)
        assert sig.symbol == "BTC/USDT"
        assert sig.technicals_breakdown is not None
        assert sig.sentiment_breakdown is not None
        assert sig.timestamp != ""
        assert sig.entry_price == 50000.0
        assert sig.stop_loss > 0
        assert sig.target > 0

    def test_buy_target_above_entry(self):
        """For a BUY signal, target should be above entry and SL below."""
        sig = evaluate("BTC/USDT", _tech(90.0), _sent(85.0))
        assert sig is not None
        assert sig.direction == "BUY"
        assert sig.target > sig.entry_price
        assert sig.stop_loss < sig.entry_price

    def test_sell_target_below_entry(self):
        """For a SELL signal, target should be below entry and SL above."""
        sig = evaluate("SOL/USDT", _tech(15.0, "BEARISH"), _sent(10.0, "Bearish"))
        assert sig is not None
        assert sig.direction == "SELL"
        assert sig.target < sig.entry_price
        assert sig.stop_loss > sig.entry_price
