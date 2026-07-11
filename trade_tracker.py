"""
Trade Tracker — Monitors active trades and sends continuous updates.

After a signal is generated, the tracker stores the trade and keeps
monitoring the live price on every scan cycle.  It sends periodic
Telegram updates showing P&L, and auto-closes the trade when
stop-loss or take-profit is hit.
"""

import time
import logging
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum

import config
from data_pipeline import fetch_ohlcv, DataFetchError, fetch_live_prices
from sentiment import fetch_sentiment
import report_tracker
import executor

logger = logging.getLogger(__name__)


class TradeStatus(Enum):
    ACTIVE = "ACTIVE"
    TARGET_HIT = "TARGET_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    MANUALLY_CLOSED = "MANUALLY_CLOSED"
    EXPIRED = "EXPIRED"


@dataclass
class ActiveTrade:
    """Represents a trade being tracked after signal generation."""

    symbol: str
    direction: str                       # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    target: float
    confidence: float
    amount: float = 0.0
    sl_order_id: str = ""
    tp_order_id: str = ""
    atr: float = 0.0                     # ATR at signal time (for trailing stop)
    opened_at: float = 0.0              # unix timestamp
    last_update_sent: float = 0.0       # unix timestamp of last update
    current_price: float = 0.0
    peak_price: float = 0.0             # best price since entry
    worst_price: float = 0.0            # worst price since entry
    update_count: int = 0
    trailing_sl_active: bool = False     # whether trailing stop has been activated
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
    def notional_size(self) -> float:
        """The total position size in quote currency."""
        return self.amount * self.entry_price

    @property
    def margin_deployed(self) -> float:
        """The actual absolute margin (USDT) locked in this trade."""
        import config
        return self.notional_size / config.LEVERAGE

    @property
    def pnl_usd(self) -> float:
        """Unrealised P&L in actual US Dollars, using real dynamic sizing amount."""
        gross_profit = (self.pnl_percent / 100) * self.notional_size
        # Binance taker fee is typically 0.05% per side, so 0.1% total on the notional size
        estimated_fees = self.notional_size * 0.001 
        return gross_profit - estimated_fees

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
_TRADES_FILE = "trades.json"

def _load_trades():
    global _active_trades
    if os.path.exists(_TRADES_FILE):
        try:
            with open(_TRADES_FILE, "r") as f:
                data = json.load(f)
                for sym, t_data in data.items():
                    if "status" in t_data:
                        t_data["status"] = TradeStatus(t_data["status"])
                    _active_trades[sym] = ActiveTrade(**t_data)
            logger.info("Loaded %d active trades from %s", len(_active_trades), _TRADES_FILE)
        except Exception as e:
            logger.error("Failed to load trades: %s", e)

def _save_trades():
    try:
        with open(_TRADES_FILE, "w") as f:
            data = {sym: asdict(t) for sym, t in _active_trades.items()}
            for t_data in data.values():
                if isinstance(t_data["status"], Enum):
                    t_data["status"] = t_data["status"].value
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Failed to save trades: %s", e)

_load_trades()


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
        amount=signal.amount,
        sl_order_id=signal.sl_order_id,
        tp_order_id=signal.tp_order_id,
        atr=signal.technicals_breakdown.get("atr", 0.0),
    )

    if signal.symbol in _active_trades:
        logger.info(
            "Replacing existing trade for %s with new %s signal",
            signal.symbol, signal.direction,
        )

    _active_trades[signal.symbol] = trade
    _save_trades()
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
        if getattr(config, "AUTO_TRADE_ENABLED", False):
            executor.execute_exit(trade)
        trade.status = status
        _save_trades()
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
    
    symbols = list(_active_trades.keys())
    live_prices = fetch_live_prices(symbols)

    for symbol in symbols:
        # Guard: symbol may have been removed in a previous iteration
        if symbol not in _active_trades:
            continue
        trade = _active_trades[symbol]
        
        # ── Check Expiry ──────────────────────────────────────────────
        elapsed = time.time() - trade.opened_at
        if elapsed > config.MAX_TRADE_DURATION:
            trade.status = TradeStatus.EXPIRED
            trade.update_count += 1
            updates.append({"trade": trade, "event": "expired"})
            if getattr(config, "AUTO_TRADE_ENABLED", False):
                executor.execute_exit(trade)
            _active_trades.pop(symbol)
            _save_trades()
            report_tracker.record_closed_trade(trade, "expired")
            logger.info("⏱️ TRADE EXPIRED for %s %s (Hit max duration) | P&L: %+.2f%%", 
                        trade.direction, symbol, trade.pnl_percent)
            continue

        live_price = live_prices.get(symbol)
        if live_price is None:
            logger.warning("Could not fetch live price for tracked trade %s", symbol)
            continue
            
        # ── Verify Position Exists on Exchange (Liquidated / Hit Check) ────
        # GRACE PERIOD: Don't check brand-new trades — give Binance time to propagate
        trade_age = time.time() - trade.opened_at
        if trade_age > 60 and not executor.is_position_open(symbol):
            # The exchange closed this position! Let's see if it was a Win or Loss.
            event = "stop_loss_hit"
            if trade.direction == "BUY" and live_price >= trade.target:
                event = "target_hit"
            elif trade.direction == "SELL" and live_price <= trade.target:
                event = "target_hit"
                
            logger.info("🚨 Hard Stop triggered on exchange for %s! Result: %s", symbol, event.upper())
            trade.status = TradeStatus.TARGET_HIT if event == "target_hit" else TradeStatus.STOP_LOSS_HIT
            trade.current_price = live_price
            trade.update_count += 1
            updates.append({"trade": trade, "event": event})
            
            if getattr(config, "AUTO_TRADE_ENABLED", False):
                executor.execute_exit(trade)
            _active_trades.pop(symbol)
            _save_trades()
            report_tracker.record_closed_trade(trade, event)
            continue

        # Set current_price FIRST so all exit alerts report accurate live price
        trade.current_price = live_price
        if trade.direction == "BUY":
            trade.peak_price = max(trade.peak_price, live_price)
            trade.worst_price = min(trade.worst_price, live_price)
        else:
            trade.peak_price = min(trade.peak_price, live_price)
            trade.worst_price = max(trade.worst_price, live_price)

        # ── Check News / Sentiment for Emergency Exit ───────────────
        try:
            sent = fetch_sentiment(symbol)
            sent_label = sent.get("label", "Neutral")
            
            is_emergency = False
            if trade.direction == "BUY" and sent_label == "Bearish":
                is_emergency = True
            elif trade.direction == "SELL" and sent_label == "Bullish":
                is_emergency = True
                
            if is_emergency:
                logger.warning("🚨 EMERGENCY EXIT for %s! News turned %s against our %s position.", 
                               symbol, sent_label, trade.direction)
                trade.status = TradeStatus.MANUALLY_CLOSED
                trade.update_count += 1
                updates.append({"trade": trade, "event": "emergency_exit"})
                if getattr(config, "AUTO_TRADE_ENABLED", False):
                    executor.execute_exit(trade)
                _active_trades.pop(symbol)
                _save_trades()
                report_tracker.record_closed_trade(trade, "emergency_exit")
                continue
                
        except Exception as exc:
            logger.debug("Could not verify news for %s: %s", symbol, exc)

        # ── Trailing Stop Loss ────────────────────────────────────────
        if config.TRAILING_STOP_ENABLED and trade.atr > 0:
            tp_progress = trade.distance_to_target_pct
            # Activate trailing once price crosses activation threshold (default 50%)
            if tp_progress >= config.TRAILING_STOP_ACTIVATION_PCT * 100:
                trail_distance = trade.atr * config.TRAILING_STOP_DISTANCE_ATR
                inverse_side = "sell" if trade.direction == "BUY" else "buy"
                
                if trade.direction == "BUY":
                    new_sl = trade.peak_price - trail_distance
                    if new_sl > trade.stop_loss:
                        old_sl = trade.stop_loss
                        new_sl = round(new_sl, 6)
                        new_id = executor.move_hard_stop(symbol, trade.sl_order_id, new_sl, inverse_side, trade.amount)
                        if new_id:
                            trade.sl_order_id = new_id
                            trade.stop_loss = new_sl
                            trade.trailing_sl_active = True
                            logger.info("📈 Trailing SL physically moved UP on exchange for %s: %.6f → %.6f", symbol, old_sl, trade.stop_loss)
                else:  # SELL
                    new_sl = trade.peak_price + trail_distance
                    if new_sl < trade.stop_loss:
                        old_sl = trade.stop_loss
                        new_sl = round(new_sl, 6)
                        new_id = executor.move_hard_stop(symbol, trade.sl_order_id, new_sl, inverse_side, trade.amount)
                        if new_id:
                            trade.sl_order_id = new_id
                            trade.stop_loss = new_sl
                            trade.trailing_sl_active = True
                            logger.info("📉 Trailing SL physically moved DOWN on exchange for %s: %.6f → %.6f", symbol, old_sl, trade.stop_loss)

        # ── Check SL / TP (ONLY in paper-trading mode) ────────────────
        # When AUTO_TRADE is ON, Binance's Hard Stops handle exits.
        # Running soft checks alongside would cause false double-closures.
        if not getattr(config, "AUTO_TRADE_ENABLED", False):
            hit_status = _check_sl_tp(trade)

            if hit_status == TradeStatus.TARGET_HIT:
                trade.status = TradeStatus.TARGET_HIT
                trade.update_count += 1
                updates.append({"trade": trade, "event": "target_hit"})
                _active_trades.pop(symbol)
                _save_trades()
                report_tracker.record_closed_trade(trade, "target_hit")
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
                _save_trades()
                report_tracker.record_closed_trade(trade, "stop_loss_hit")
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
            _save_trades()  # Checkpoint state to save updated counters
            logger.info(
                "📊 Update #%d for %s: price=%.6f, P&L=%+.2f%% ($%+.2f), TP dist=%.1f%%",
                trade.update_count, symbol, live_price,
                trade.pnl_percent, trade.pnl_usd, trade.distance_to_target_pct,
            )

    return updates


def get_portfolio_summary() -> dict:
    """Build a summary of all active trades."""
    if not _active_trades:
        return {"count": 0, "trades": []}

    trade_summaries = []
    total_pnl = 0.0
    total_pnl_usd = 0.0

    for symbol, trade in _active_trades.items():
        trade_summaries.append({
            "symbol": symbol,
            "direction": trade.direction,
            "pnl_percent": round(trade.pnl_percent, 2),
            "pnl_usd": round(trade.pnl_usd, 2),
            "margin": round(trade.margin_deployed, 2),
            "duration": trade.duration_str,
            "distance_to_target": round(trade.distance_to_target_pct, 1),
        })
        total_pnl += trade.pnl_percent
        total_pnl_usd += trade.pnl_usd

    return {
        "count": len(_active_trades),
        "avg_pnl": round(total_pnl / len(_active_trades), 2) if _active_trades else 0.0,
        "total_pnl_usd": round(total_pnl_usd, 2),
        "trades": trade_summaries,
    }
