"""
Signal Engine — Decision matrix that fuses technicals and sentiment.

Generates a Buy/Sell signal ONLY when confidence ≥ CONFIDENCE_THRESHOLD.
Enforces a per-asset cooldown to prevent alert spam.
"""

import time
import json
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Immutable record representing a generated signal."""

    symbol: str
    direction: str                    # "BUY" or "SELL"
    confidence: float                 # 0.0 – 1.0
    entry_price: float = 0.0         # current market price
    stop_loss: float = 0.0           # ATR-based stop loss
    target: float = 0.0              # risk-reward based target
    amount: float = 0.0              # executed units
    sl_order_id: str = ""            # hard stop loss exchange id
    tp_order_id: str = ""            # hard take profit exchange id
    technicals_breakdown: dict = field(default_factory=dict)
    sentiment_breakdown: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = (
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            )


# ── Cooldown tracking (persisted to disk) ────────────────────────────
_last_signal_time: dict[str, float] = {}
_COOLDOWN_FILE = "cooldowns.json"


def _load_cooldowns():
    global _last_signal_time
    if os.path.exists(_COOLDOWN_FILE):
        try:
            with open(_COOLDOWN_FILE, "r") as f:
                _last_signal_time = json.load(f)
        except Exception:
            _last_signal_time = {}


def _save_cooldowns():
    try:
        with open(_COOLDOWN_FILE, "w") as f:
            json.dump(_last_signal_time, f)
    except Exception as e:
        logger.warning("Could not save cooldowns: %s", e)


_load_cooldowns()


def _is_cooled_down(symbol: str) -> bool:
    """Return True if enough time has passed since the last signal for *symbol*."""
    last = _last_signal_time.get(symbol, 0.0)
    elapsed = time.time() - last
    if elapsed < config.COOLDOWN_SECONDS:
        remaining = config.COOLDOWN_SECONDS - elapsed
        logger.info(
            "Cooldown active for %s — %.0fs remaining", symbol, remaining
        )
        return False
    return True


def _record_signal(symbol: str) -> None:
    """Mark the current time as the last signal time for *symbol*."""
    _last_signal_time[symbol] = time.time()
    _save_cooldowns()


def reset_cooldown(symbol: str | None = None) -> None:
    """Reset cooldown for one or all symbols (useful in tests)."""
    if symbol:
        _last_signal_time.pop(symbol, None)
    else:
        _last_signal_time.clear()


def _compute_price_levels(
    direction: str, current_price: float, atr: float, fib_levels: dict = None
) -> tuple[float, float, float]:
    """
    Compute entry, stop-loss, and target from ATR, optionally using Fibonacci extensions/retracements.
    """
    risk = atr * config.STOP_LOSS_ATR_MULTIPLIER
    use_fib = getattr(config, "USE_FIB_TARGETS", True) and fib_levels
    
    if direction == "BUY":
        stop_loss = current_price - risk
        target = current_price + (risk * config.RISK_REWARD_RATIO)
        if use_fib:
            exts = [v for k, v in fib_levels.items() if k >= 1.0 and v > current_price]
            if exts:
                target = min(exts)
            
            rets = [v for k, v in fib_levels.items() if k <= 1.0 and v < current_price]
            if rets:
                closest_ret = max(rets)
                fib_sl = closest_ret - (atr * 0.5)
                if current_price - fib_sl < risk * 1.5:
                    stop_loss = fib_sl
                    
    else:  # SELL
        stop_loss = current_price + risk
        target = current_price - (risk * config.RISK_REWARD_RATIO)
        if use_fib:
            exts = [v for k, v in fib_levels.items() if v < current_price]
            if exts:
                target = max(exts)
                
            rets = [v for k, v in fib_levels.items() if v > current_price]
            if rets:
                closest_ret = min(rets)
                fib_sl = closest_ret + (atr * 0.5)
                if fib_sl - current_price < risk * 1.5:
                    stop_loss = fib_sl

    return current_price, round(stop_loss, 6), round(target, 6)

def evaluate(
    symbol: str,
    technical_scores: dict,
    sentiment_scores: dict,
) -> Signal | None:
    """
    Fuse technical and sentiment scores into a trading signal.

    Parameters
    ----------
    symbol : str              e.g. "BTC/USDT"
    technical_scores : dict   from technicals.compute_technicals()
    sentiment_scores : dict   from sentiment.fetch_sentiment()

    Returns
    -------
    Signal  if confidence ≥ threshold and cooldown has expired
    None    otherwise
    """
    # ── Cooldown gate ────────────────────────────────────────────────
    if not _is_cooled_down(symbol):
        return None

    # ── Weighted confidence ──────────────────────────────────────────
    tech_score = technical_scores.get("composite_score", 50.0)  # 0-100
    sent_score = sentiment_scores.get("score", 50.0)            # 0-100

    # Normalise to 0–1 for the confidence calculation
    tech_norm = tech_score / 100.0
    sent_norm = sent_score / 100.0

    raw_confidence = (
        config.TECHNICAL_WEIGHT * tech_norm
        + config.SENTIMENT_WEIGHT * sent_norm
    )

    # For bearish signals, confidence comes from low scores
    if 0.45 <= raw_confidence <= 0.55:
        logger.info("%s — Neutral score %.2f, no clear signal.", symbol, raw_confidence)
        return None
    elif raw_confidence < 0.45:
        confidence = 1.0 - raw_confidence  # e.g. 0.2 → 0.8 confidence
        direction = "SELL"
    else:
        confidence = raw_confidence
        direction = "BUY"

    confidence = round(confidence, 4)

    logger.info(
        "%s — tech=%.1f, sent=%.1f, conf=%.2f%%, dir=%s",
        symbol, tech_score, sent_score, confidence * 100, direction,
    )

    # ── Threshold gate ───────────────────────────────────────────────
    if confidence < config.CONFIDENCE_THRESHOLD:
        logger.info(
            "%s confidence (%.2f%%) below threshold (%.0f%%) — no signal",
            symbol, confidence * 100, config.CONFIDENCE_THRESHOLD * 100,
        )
        return None

    # ── Volume Gate (hard filter) ─────────────────────────────────────
    volume_ratio = technical_scores.get("volume_ratio", 1.0)
    if volume_ratio < config.VOLUME_GATE_RATIO:
        logger.info("%s — Volume too low (%.2fx < %.2fx gate) — skipping signal",
                    symbol, volume_ratio, config.VOLUME_GATE_RATIO)
        return None


    # ── Institutional Filters (VWAP & EMA20) ──────────────────────────────────
    current_price = technical_scores.get("current_price", 0.0)
    vwap = technical_scores.get("vwap", 0.0)
    ema20 = technical_scores.get("ema20", 0.0)
    
    if getattr(config, "USE_VWAP_FILTER", True) and vwap > 0:
        if direction == "BUY" and current_price < vwap:
            logger.info("%s — Price (%.4f) below Daily VWAP (%.4f). Blocking BUY signal.", symbol, current_price, vwap)
            return None
        elif direction == "SELL" and current_price > vwap:
            logger.info("%s — Price (%.4f) above Daily VWAP (%.4f). Blocking SELL signal.", symbol, current_price, vwap)
            return None
            
    if getattr(config, "USE_EMA20_TRIGGER", True) and ema20 > 0:
        if direction == "BUY" and current_price < ema20:
            logger.info("%s — Price (%.4f) below 5m 20 EMA (%.4f). Blocking BUY signal.", symbol, current_price, ema20)
            return None
        elif direction == "SELL" and current_price > ema20:
            logger.info("%s — Price (%.4f) above 5m 20 EMA (%.4f). Blocking SELL signal.", symbol, current_price, ema20)
            return None

    # ── Price levels ─────────────────────────────────────────────────
    current_price = technical_scores.get("current_price", 0.0)
    atr = technical_scores.get("atr", 0.0)
    fib_levels = technical_scores.get("fib_levels", {})
    entry_price, stop_loss, target = _compute_price_levels(
        direction, current_price, atr, fib_levels
    )

    # ── Build signal ─────────────────────────────────────────────────
    signal = Signal(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        technicals_breakdown={
            "rsi": technical_scores.get("rsi"),
            "rsi_score": technical_scores.get("rsi_score"),
            "volume_ratio": technical_scores.get("volume_ratio"),
            "volume_score": technical_scores.get("volume_score"),
            "momentum_score": technical_scores.get("momentum_score"),
            "trend_score": technical_scores.get("trend_score"),
            "composite_score": tech_score,
            "bias": technical_scores.get("signal_bias"),
            "atr": technical_scores.get("atr", 0.0),
            "ema20": technical_scores.get("ema20", 0.0),
            "vwap": technical_scores.get("vwap", 0.0),
            "fvg_status": technical_scores.get("fvg_status", "NONE"),
            "sweep_status": technical_scores.get("sweep_status", "NONE"),
            "smc_score": technical_scores.get("smc_score", 50.0),
        },
        sentiment_breakdown={
            "score": sent_score,
            "label": sentiment_scores.get("label"),
            "headline_count": sentiment_scores.get("headline_count", 0),
            "bullish_count": sentiment_scores.get("bullish_count", 0),
            "bearish_count": sentiment_scores.get("bearish_count", 0),
            "neutral_count": sentiment_scores.get("neutral_count", 0),
        },
    )

    _record_signal(symbol)
    logger.info("🚨 Signal generated: %s %s @ %.2f%% confidence | Entry: %s | SL: %s | TP: %s",
                signal.direction, symbol, confidence * 100,
                entry_price, stop_loss, target)
    return signal
