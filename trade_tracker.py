"""
Trade Tracker — Monitors active trades and sends continuous updates.

After a signal is generated, the tracker stores the trade and keeps
monitoring the live price on every scan cycle.  It sends periodic
Telegram updates showing P&L, and auto-closes the trade when
stop-loss or take-profit is hit.
"""

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import config
from data_pipeline import fetch_ohlcv, DataFetchError

logger = logging.getLogger(__name__)


class TradeStatus(Enum):
    ACTIVE = "ACTIVE"
    TARGET_HIT = "TARGET_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    MANUALLY_CLOSED = "MANUALLY_CLOSED"


@dataclass
class ActiveTrade:
    """Represents a trade being tracked after signal generation."""

    symbol: str
    direction: str                       # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    target: float
    confidence: float
    opened_at: float = 0.0              # unix timestamp
    last_update_sent: float = 0.0       # unix timestamp of last update
    current_price: float = 0.0
    peak_price: float = 0.0             # best price since entry
    worst_price: float = 0.0            # worst price since entry
    update_count: int = 0
    status: TradeStatus = TradeStatus.ACTIVE

    def __post_init__(self):
        if self.opened_at == 0.0:
            self.opened_at = time.time()
        if self.current_price == 0.0:
            self.current_price = self.entry_price
        if self.peak_price == 0.0:
            self.peak_price = self.entry_price
        if self.worst_price == 0.0:
            self.worst_price = self.entry_price

    @property
    def pnl_percent(self) -> float:
        """Unrealised P&L as a percentage."""
        if self.entry_price == 0:
            return 0.0
        if self.direction == "BUY":
            return ((self.current_price - self.entry_price) / self.entry_price) * 100
        else:  # SELL
            return ((self.entry_price - self.current_price) / self.entry_price) * 100

    @property
    def pnl_absolute(self) -> float:
        """Unrealised P&L in quote currency (per unit)."""
        if self.direction == "BUY":
            return self.current_price - self.entry_price
        else:
            return self.entry_price - self.current_price

    @property
    def distance_to_target_pct(self) -> float:
        """How far the price is from the target, as % of total range."""
        total_range = abs(self.target - self.entry_price)
        if total_range == 0:
            return 0.0
        if self.direction == "BUY":
            progress = self.current_price - self.entry_price
        else:
            progress = self.entry_price - self.current_price
        return (progress / total_range) * 100

    @property
    def distance_to_sl_pct(self) -> float:
        """How far the price is from the stop-loss, as % of total range."""
        total_range = abs(self.entry_price - self.stop_loss)
        if total_range == 0:
            return 0.0
        if self.direction == "BUY":
            distance = self.current_price - self.stop_loss
        else:
            distance = self.stop_loss - self.current_price
        return (distance / total_range) * 100

    @property
    def duration_str(self) -> str:
        """Human-readable duration since trade opened."""
        elapsed = time.time() - self.opened_at
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


# ── Active trades storage ────────────────────────────────────────────
_active_trades: dict[str, ActiveTrade] = {}


def get_active_trades() -> dict[str, ActiveTrade]:
    """Return a copy of the active trades dict."""
    return dict(_active_trades)


def get_trade(symbol: str) -> ActiveTrade | None:
    """Get the active trade for a symbol, if any."""
    return _active_trades.get(symbol)


def has_active_trade(symbol: str) -> bool:
    """Check if there's an active trade for a symbol."""
    return symbol in _active_trades


def register_trade(signal) -> ActiveTrade:
    """
    Register a new active trade from a Signal object.

    If there's already an active trade for the symbol, it will be replaced.
    """
    trade = ActiveTrade(
        symbol=signal.symbol,
        direction=signal.direction,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target=signal.target,
        confidence=signal.confidence,
    )

    if signal.symbol in _active_trades:
        logger.info(
            "Replacing existing trade for %s with new %s signal",
            signal.symbol, signal.direction,
        )

    _active_trades[signal.symbol] = trade
    logger.info(
        "📋 Trade registered: %s %s @ %.6f | SL: %.6f | TP: %.6f",
        signal.direction, signal.symbol, signal.entry_price,
        signal.stop_loss, signal.target,
    )
    return trade


def close_trade(symbol: str, status: TradeStatus = TradeStatus.MANUALLY_CLOSED) -> ActiveTrade | None:
    """
    Close and remove an active trade. Returns the closed trade or None.
    """
    trade = _active_trades.pop(symbol, None)
    if trade:
        trade.status = status
        logger.info(
            "🏁 Trade closed: %s %s | Status: %s | Final P&L: %+.2f%%",
            trade.direction, symbol, status.value, trade.pnl_percent,
        )
    return trade


def _check_sl_tp(trade: ActiveTrade) -> TradeStatus:
    """Check if stop-loss or take-profit has been hit."""
    if trade.direction == "BUY":
        if trade.current_price <= trade.stop_loss:
            return TradeStatus.STOP_LOSS_HIT
        if trade.current_price >= trade.target:
            return TradeStatus.TARGET_HIT
    else:  # SELL
        if trade.current_price >= trade.stop_loss:
            return TradeStatus.STOP_LOSS_HIT
        if trade.current_price <= trade.target:
            return TradeStatus.TARGET_HIT

    return TradeStatus.ACTIVE


def _should_send_update(trade: ActiveTrade) -> bool:
    """Determine if it's time to send a periodic update."""
    now = time.time()
    elapsed_since_update = now - trade.last_update_sent
    return elapsed_since_update >= config.TRADE_UPDATE_INTERVAL


def update_trades(dry_run: bool = False) -> list[dict]:
    """
    Check all active trades: update prices, detect SL/TP hits,
    send periodic updates.

    Returns a list of update dicts for the notifier to process.

    Each dict has keys:
        trade    — ActiveTrade object
        event    — "update" | "target_hit" | "stop_loss_hit"
    """
    if not _active_trades:
        return []

    updates = []

    # Iterate over a copy since we may modify the dict
    for symbol in list(_active_trades.keys()):
        trade = _active_trades[symbol]

        # ── Fetch current price ──────────────────────────────────────
        try:
            df = fetch_ohlcv(symbol, limit=1)
            live_price = float(df["close"].iloc[-1])
        except (DataFetchError, Exception) as exc:
            logger.warning(
                "Could not fetch price for tracked trade %s: %s", symbol, exc
            )
            continue

        # ── Update trade state ───────────────────────────────────────
        trade.current_price = live_price

        if trade.direction == "BUY":
            trade.peak_price = max(trade.peak_price, live_price)
            trade.worst_price = min(trade.worst_price, live_price)
        else:
            trade.peak_price = min(trade.peak_price, live_price)
            trade.worst_price = max(trade.worst_price, live_price)

        # ── Check SL / TP ────────────────────────────────────────────
        hit_status = _check_sl_tp(trade)

        if hit_status == TradeStatus.TARGET_HIT:
            trade.status = TradeStatus.TARGET_HIT
            trade.update_count += 1
            updates.append({"trade": trade, "event": "target_hit"})
            _active_trades.pop(symbol)
            logger.info(
                "🎯 TARGET HIT for %s %s @ %.6f | P&L: %+.2f%%",
                trade.direction, symbol, live_price, trade.pnl_percent,
            )
            continue

        if hit_status == TradeStatus.STOP_LOSS_HIT:
            trade.status = TradeStatus.STOP_LOSS_HIT
            trade.update_count += 1
            updates.append({"trade": trade, "event": "stop_loss_hit"})
            _active_trades.pop(symbol)
            logger.info(
                "🛑 STOP LOSS HIT for %s %s @ %.6f | P&L: %+.2f%%",
                trade.direction, symbol, live_price, trade.pnl_percent,
            )
            continue

        # ── Periodic update ──────────────────────────────────────────
        if _should_send_update(trade):
            trade.update_count += 1
            trade.last_update_sent = time.time()
            updates.append({"trade": trade, "event": "update"})
            logger.info(
                "📊 Update #%d for %s: price=%.6f, P&L=%+.2f%%, TP dist=%.1f%%",
                trade.update_count, symbol, live_price,
                trade.pnl_percent, trade.distance_to_target_pct,
            )

    return updates


def get_portfolio_summary() -> dict:
    """Build a summary of all active trades."""
    if not _active_trades:
        return {"count": 0, "trades": []}

    trade_summaries = []
    total_pnl = 0.0

    for symbol, trade in _active_trades.items():
        trade_summaries.append({
            "symbol": symbol,
            "direction": trade.direction,
            "pnl_percent": round(trade.pnl_percent, 2),
            "duration": trade.duration_str,
            "distance_to_target": round(trade.distance_to_target_pct, 1),
        })
        total_pnl += trade.pnl_percent

    return {
        "count": len(_active_trades),
        "avg_pnl": round(total_pnl / len(_active_trades), 2),
        "trades": trade_summaries,
    }
