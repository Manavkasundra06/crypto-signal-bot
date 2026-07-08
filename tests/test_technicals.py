"""Tests for technicals.py — RSI and Volume scoring."""

import pandas as pd
import numpy as np

from technicals import compute_technicals, _rsi_to_score, _volume_to_score


def _make_ohlcv(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of closing prices."""
    n = len(closes)
    if volumes is None:
        volumes = [1000.0] * n
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="5min"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes,
    })


class TestRsiToScore:
    def test_oversold_gives_high_score(self):
        assert _rsi_to_score(20.0) == 80.0

    def test_overbought_gives_low_score(self):
        assert _rsi_to_score(85.0) == 15.0

    def test_neutral_rsi(self):
        assert _rsi_to_score(50.0) == 50.0

    def test_nan_returns_neutral(self):
        assert _rsi_to_score(float("nan")) == 50.0

    def test_clamped_at_zero(self):
        assert _rsi_to_score(110.0) == 0.0

    def test_clamped_at_hundred(self):
        assert _rsi_to_score(-10.0) == 100.0


class TestVolumeToScore:
    def test_double_volume_scores_high(self):
        score = _volume_to_score(2000.0, 1000.0)
        assert score == 100.0

    def test_average_volume_scores_fifty(self):
        score = _volume_to_score(1000.0, 1000.0)
        assert score == 50.0

    def test_zero_sma_returns_neutral(self):
        assert _volume_to_score(1000.0, 0.0) == 50.0

    def test_nan_sma_returns_neutral(self):
        assert _volume_to_score(1000.0, float("nan")) == 50.0


class TestComputeTechnicals:
    def test_returns_expected_keys(self):
        # 100 candles with a gentle uptrend
        closes = list(np.linspace(100, 120, 100))
        df = _make_ohlcv(closes)
        result = compute_technicals(df)

        expected_keys = {
            "rsi", "rsi_score", "volume_ratio", "volume_score",
            "composite_score", "signal_bias", "current_price", "atr"
        }
        assert expected_keys == set(result.keys())

    def test_bias_is_valid_label(self):
        closes = list(np.linspace(100, 120, 100))
        df = _make_ohlcv(closes)
        result = compute_technicals(df)
        assert result["signal_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")

    def test_scores_are_bounded(self):
        closes = list(np.linspace(100, 120, 100))
        df = _make_ohlcv(closes)
        result = compute_technicals(df)
        assert 0 <= result["rsi_score"] <= 100
        assert 0 <= result["volume_score"] <= 100
        assert 0 <= result["composite_score"] <= 100
