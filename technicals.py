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



def _fibonacci_score(df: pd.DataFrame) -> dict:
    """
    Calculate the macro swing high and low over the lookback period,
    derive the Fibonacci retracement levels, and score the current price.
    """
    if len(df) < 50:
        return {"score": 50.0, "levels": {}}
        
    lookback = getattr(config, "FIB_LOOKBACK_PERIOD", 200)
    df_lookback = df.tail(lookback)
    
    swing_high = float(df_lookback["high"].max())
    swing_low = float(df_lookback["low"].min())
    current_price = float(df["close"].iloc[-1])
    
    diff = swing_high - swing_low
    if diff == 0:
        return {"score": 50.0, "levels": {}}
        
    levels = {
        0.0: swing_low,
        0.236: swing_low + diff * 0.236,
        0.382: swing_low + diff * 0.382,
        0.5: swing_low + diff * 0.5,
        0.618: swing_low + diff * 0.618,
        0.786: swing_low + diff * 0.786,
        1.0: swing_high,
        1.272: swing_high + diff * 0.272,
        1.618: swing_high + diff * 0.618,
    }
    
    pocket_mid = (levels[0.5] + levels[0.618]) / 2.0
    pocket_width = abs(levels[0.618] - levels[0.5])
    
    dist = abs(current_price - pocket_mid)
    
    if dist < pocket_width:
        score = 100.0
    else:
        decay = (dist / diff) * 100.0
        score = max(50.0, 100.0 - decay)
        
    return {
        "score": round(score, 2),
        "swing_high": swing_high,
        "swing_low": swing_low,
        "levels": levels
    }

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
    # ── Fibonacci (1h) ────────────────────────────────────────────────────────
    fib_data = _fibonacci_score(df_1h)
    fib_score = fib_data.get("score", 50.0)
    fib_levels = fib_data.get("levels", {})

    # ── Composite ────────────────────────────────────────────────────────────
    fib_weight = getattr(config, "FIB_WEIGHT", 0.2)
    rem = 1.0 - fib_weight
    composite = (
        (0.25 * rem) * rsi_score
        + (0.15 * rem) * volume_score
        + (0.30 * rem) * momentum_score
        + (0.30 * rem) * trend_score
        + fib_weight * fib_score
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
        "fib_score": fib_score,
        "fib_levels": fib_levels,
        "swing_high": fib_data.get("swing_high"),
        "swing_low": fib_data.get("swing_low"),
    }

    logger.info("Multi-Timeframe Techs: RSI=%.0f Vol=%.1f Momentum=%.0f Trend=%.0f -> %s", 
                rsi_score, volume_score, momentum_score, trend_score, result["signal_bias"])
    return result
