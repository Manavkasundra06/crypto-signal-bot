"""
Report Tracker — Logs every closed trade and generates an end-of-day report.

Throughout the day, every closed trade (TP hit, SL hit, expired, emergency exit)
is appended to a JSON file. At the configured daily report time, the main loop
calls get_daily_report() to build a performance summary and resets the log.
"""

import json
import os
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_REPORT_FILE = "daily_trades.json"


# ── Record a closed trade ─────────────────────────────────────────────

def record_closed_trade(trade, event: str) -> None:
    """
    Append a completed trade to today's report log.

    Parameters
    ----------
    trade : ActiveTrade   the closed trade object
    event : str           "target_hit" | "stop_loss_hit" | "expired" | "emergency_exit"
    """
    record = {
        "symbol":      trade.symbol,
        "direction":   trade.direction,
        "event":       event,
        "entry_price": trade.entry_price,
        "exit_price":  round(trade.current_price, 6),
        "stop_loss":   trade.stop_loss,
        "target":      trade.target,
        "pnl_percent": round(trade.pnl_percent, 3),
        "pnl_absolute": round(trade.pnl_absolute, 6),
        "duration":    trade.duration_str,
        "opened_at":   trade.opened_at,
        "closed_at":   time.time(),
        "confidence":  round(trade.confidence * 100, 1),
        "update_count": trade.update_count,
    }

    existing = _load_report_file()
    existing.append(record)
    _save_report_file(existing)
    logger.info("📝 Trade logged to daily report: %s %s | %s | PnL: %+.2f%%",
                trade.direction, trade.symbol, event, trade.pnl_percent)


# ── Load / Save helpers ────────────────────────────────────────────────

def _load_report_file() -> list:
    if os.path.exists(_REPORT_FILE):
        try:
            with open(_REPORT_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Could not load daily report file: %s", e)
    return []


def _save_report_file(data: list) -> None:
    try:
        with open(_REPORT_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Could not save daily report file: %s", e)


# ── Build the daily report ─────────────────────────────────────────────

def get_daily_report() -> dict:
    """
    Build and return a performance summary of all trades closed today.

    Returns
    -------
    dict with keys:
        date, total_trades, wins, losses, expired, emergency_exits,
        win_rate, total_pnl, avg_pnl, best_trade, worst_trade, trades
    """
    trades = _load_report_file()
    if not trades:
        return {"total_trades": 0, "trades": []}

    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")

    wins = [t for t in trades if t["event"] == "target_hit"]
    losses = [t for t in trades if t["event"] == "stop_loss_hit"]
    expired = [t for t in trades if t["event"] == "expired"]
    emergency = [t for t in trades if t["event"] == "emergency_exit"]

    all_pnl = [t["pnl_percent"] for t in trades]
    total_pnl = round(sum(all_pnl), 2)
    avg_pnl = round(total_pnl / len(trades), 2) if trades else 0.0
    win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0.0

    best = max(trades, key=lambda t: t["pnl_percent"]) if trades else None
    worst = min(trades, key=lambda t: t["pnl_percent"]) if trades else None

    return {
        "date":            date_str,
        "total_trades":    len(trades),
        "wins":            len(wins),
        "losses":          len(losses),
        "expired":         len(expired),
        "emergency_exits": len(emergency),
        "win_rate":        win_rate,
        "total_pnl":       total_pnl,
        "avg_pnl":         avg_pnl,
        "best_trade":      best,
        "worst_trade":     worst,
        "trades":          trades,
    }


def reset_daily_report() -> None:
    """Clear the daily trade log after report has been sent."""
    _save_report_file([])
    logger.info("🗑️ Daily report log reset for new day.")
