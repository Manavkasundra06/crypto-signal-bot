"""
Technical Analysis — Computes RSI and Volume indicators using pandas-ta.

All indicators are normalised to a 0–100 score where:
    100 = maximally bullish
      0 = maximally bearish
     50 = neutral
"""

import logging

import pandas as pd

import config

logger = logging.getLogger(__name__)


def _rsi_to_score(rsi_value: float) -> float:
    """
    Convert a raw RSI(14) into a bullish-bias score (0–100).

    RSI < 30  → oversold  → bullish  → score 80–100
    RSI > 70  → overbought → bearish → score  0–20
    Middle zone scales linearly.
    """
    if pd.isna(rsi_value):
        return 50.0  # neutral when unavailable

    # Invert: low RSI = high score (bullish)
    score = 100.0 - rsi_value
    return max(0.0, min(100.0, score))


def _volume_to_score(current_volume: float, sma_volume: float) -> float:
    """
    Score current volume relative to its SMA.

    ratio > 1.5 → high conviction     → score ≈ 80–100
    ratio ≈ 1.0 → average             → score ≈ 50
    ratio < 0.5 → low conviction      → score ≈ 0–20
    """
    if pd.isna(sma_volume) or sma_volume == 0:
        return 50.0

    ratio = current_volume / sma_volume
    # Map ratio [0 .. 2+] → score [0 .. 100], clamped
    score = min(ratio / 2.0, 1.0) * 100.0
    return max(0.0, min(100.0, score))


def _bias_label(score: float) -> str:
    if score >= 60:
        return "BULLISH"
    elif score <= 40:
        return "BEARISH"
    return "NEUTRAL"


def compute_technicals(df: pd.DataFrame) -> dict:
    """
    Analyse a DataFrame of OHLCV candles and return scored technicals.

    Parameters
    ----------
    df : pd.DataFrame  with columns [open, high, low, close, volume]

    Returns
    -------
    dict with keys:
        rsi             — raw RSI(14) value
        rsi_score       — normalised 0–100
        volume_ratio    — current vol / SMA vol
        volume_score    — normalised 0–100
        composite_score — weighted blend (0–100)
        signal_bias     — "BULLISH" | "BEARISH" | "NEUTRAL"
    """
    # ── RSI ──────────────────────────────────────────────────────────
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = (-1 * delta.clip(upper=0))
    ema_up = up.ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    ema_down = down.ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    rs = ema_up / ema_down
    rsi_series = 100 - (100 / (1 + rs))
    
    rsi_value = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else float("nan")
    rsi_score = _rsi_to_score(rsi_value)

    # ── Volume ───────────────────────────────────────────────────────
    vol_sma = df["volume"].rolling(window=config.VOLUME_SMA_PERIOD).mean()
    current_volume = float(df["volume"].iloc[-1])
    sma_volume = float(vol_sma.iloc[-1]) if not pd.isna(vol_sma.iloc[-1]) else 0.0
    volume_ratio = round(current_volume / sma_volume, 2) if sma_volume else 0.0
    volume_score = _volume_to_score(current_volume, sma_volume)

    # ── ATR (for stop-loss / target calculation) ─────────────────────
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1/config.ATR_PERIOD, min_periods=config.ATR_PERIOD, adjust=False).mean()
    
    atr_value = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0

    # ── Current price ────────────────────────────────────────────────
    current_price = float(df["close"].iloc[-1])

    # ── Composite ────────────────────────────────────────────────────
    composite = (
        config.RSI_WEIGHT * rsi_score
        + config.VOLUME_WEIGHT * volume_score
    )
    composite = round(composite, 2)

    result = {
        "rsi": round(rsi_value, 2) if not pd.isna(rsi_value) else None,
        "rsi_score": round(rsi_score, 2),
        "volume_ratio": volume_ratio,
        "volume_score": round(volume_score, 2),
        "composite_score": composite,
        "signal_bias": _bias_label(composite),
        "current_price": round(current_price, 6),
        "atr": round(atr_value, 6),
    }

    logger.info("Technicals for latest candle: %s", result)
    return result
