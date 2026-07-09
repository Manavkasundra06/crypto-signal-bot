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


def _macd_score(df: pd.DataFrame) -> float:
    """Medium term momentum via MACD (12, 26, 9)"""
    if len(df) < 30: return 50.0
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    
    h1 = float(hist.iloc[-1])
    h2 = float(hist.iloc[-2])
    
    if h1 > 0 and h1 > h2:
        return 90.0  # Bullish gaining momentum
    elif h1 > 0:
        return 70.0  # Bullish losing momentum
    elif h1 < 0 and h1 < h2:
        return 10.0  # Bearish gaining momentum
    else:
        return 30.0  # Bearish losing momentum


def _trend_score(df: pd.DataFrame) -> float:
    """Long term trend via 50 & 200 EMA"""
    if len(df) < 200: return 50.0
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    ema200 = df["close"].ewm(span=200, adjust=False).mean()
    current = float(df["close"].iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    
    if current > e50 > e200:
        return 100.0  # Strong uptrend
    elif current > e200:
        return 65.0   # Weak uptrend
    elif current < e50 < e200:
        return 0.0    # Strong downtrend
    else:
        return 35.0   # Weak downtrend


def compute_technicals(df_5m: pd.DataFrame, df_15m: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
    """
    Analyse Multi-Timeframe OHLCV candles (5m, 15m, 1h).
    """
    # ── Entry Timing (5m) ────────────────────────────────────────────
    delta = df_5m["close"].diff()
    up = delta.clip(lower=0)
    down = (-1 * delta.clip(upper=0))
    ema_up = up.ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    ema_down = down.ewm(com=config.RSI_PERIOD - 1, adjust=False).mean()
    rs = ema_up / ema_down
    rsi_series = 100 - (100 / (1 + rs))
    
    rsi_value = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else float("nan")
    rsi_score = _rsi_to_score(rsi_value)

    # Volume (5m)
    vol_sma = df_5m["volume"].rolling(window=config.VOLUME_SMA_PERIOD).mean()
    current_volume = float(df_5m["volume"].iloc[-1])
    sma_volume = float(vol_sma.iloc[-1]) if not pd.isna(vol_sma.iloc[-1]) else 0.0
    volume_ratio = round(current_volume / sma_volume, 2) if sma_volume else 0.0
    volume_score = _volume_to_score(current_volume, sma_volume)
    
    # ATR (5m - for stop loss)
    high_low = df_5m["high"] - df_5m["low"]
    high_close = (df_5m["high"] - df_5m["close"].shift(1)).abs()
    low_close = (df_5m["low"] - df_5m["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1/config.ATR_PERIOD, min_periods=config.ATR_PERIOD, adjust=False).mean()
    atr_value = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
    
    current_price = float(df_5m["close"].iloc[-1])

    # ── Momentum (15m) ───────────────────────────────────────────────
    momentum_score = _macd_score(df_15m)
    
    # ── Trend (1h) ───────────────────────────────────────────────────
    trend_score = _trend_score(df_1h)

    # ── Composite ────────────────────────────────────────────────────
    # Reproportion weights to incorporate momentum and trend
    # volume: 15%, rsi (timing): 25%, momentum (15m): 30%, trend (1h): 30%
    composite = (
        0.25 * rsi_score
        + 0.15 * volume_score
        + 0.30 * momentum_score
        + 0.30 * trend_score
    )
    composite = round(composite, 2)

    result = {
        "rsi": round(rsi_value, 2) if not pd.isna(rsi_value) else None,
        "rsi_score": round(rsi_score, 2),
        "volume_ratio": volume_ratio,
        "volume_score": round(volume_score, 2),
        "momentum_score": round(momentum_score, 2),
        "trend_score": round(trend_score, 2),
        "composite_score": composite,
        "signal_bias": _bias_label(composite),
        "current_price": round(current_price, 6),
        "atr": round(atr_value, 6),
    }

    logger.info("Multi-Timeframe Techs: RSI=%.0f Vol=%.1f Momentum=%.0f Trend=%.0f -> %s", 
                rsi_score, volume_score, momentum_score, trend_score, result["signal_bias"])
    return result
