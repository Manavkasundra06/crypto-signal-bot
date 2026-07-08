"""
Notifier — Sends formatted signal alerts to Telegram.

Uses the Telegram Bot API (`sendMessage` with MarkdownV2 parse mode).
Includes a secondary cooldown check as a safety net.
"""

import time
import logging

import requests

import config

logger = logging.getLogger(__name__)

# ── Secondary cooldown (safety layer) ────────────────────────────────
_last_notify_time: dict[str, float] = {}


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!\\"
    escaped = []
    for ch in str(text):
        if ch in special:
            escaped.append(f"\\{ch}")
        else:
            escaped.append(ch)
    return "".join(escaped)


def _format_alert(signal) -> str:
    """Build a human-readable Telegram message from a Signal object."""
    tech = signal.technicals_breakdown
    sent = signal.sentiment_breakdown

    direction_emoji = "🟢" if signal.direction == "BUY" else "🔴"
    confidence_pct = f"{signal.confidence * 100:.1f}"

    # Extract currency name from symbol (e.g. "BTC/USDT" → "BTC")
    currency_name = signal.symbol.split("/")[0] if "/" in signal.symbol else signal.symbol

    lines = [
        f"🚨 *SIGNAL ALERT* — {_escape_md(signal.symbol)}",
        f"💰 *Currency:* {_escape_md(currency_name)}",
        "",
        f"*Direction:* {direction_emoji} {_escape_md(signal.direction)}",
        f"*Confidence:* {_escape_md(confidence_pct)}%",
        "",
        f"💵 *Price Levels*",
        f"  Entry Price: {_escape_md(str(signal.entry_price))}",
        f"  🛑 Stop Loss: {_escape_md(str(signal.stop_loss))}",
        f"  🎯 Target: {_escape_md(str(signal.target))}",
        "",
        f"📊 *Technicals* \\({_escape_md(str(int(config.TECHNICAL_WEIGHT * 100)))}% weight\\)",
        f"  RSI\\(14\\): {_escape_md(str(tech.get('rsi', 'N/A')))} → {_escape_md(str(tech.get('bias', 'N/A')))} \\(Score: {_escape_md(str(tech.get('rsi_score', 'N/A')))}\\)",
        f"  Volume: {_escape_md(str(tech.get('volume_ratio', 'N/A')))}x avg \\(Score: {_escape_md(str(tech.get('volume_score', 'N/A')))}\\)",
        f"  Tech Score: {_escape_md(str(tech.get('composite_score', 'N/A')))}",
        "",
        f"📰 *Sentiment* \\({_escape_md(str(int(config.SENTIMENT_WEIGHT * 100)))}% weight\\)",
        f"  Headlines: {_escape_md(str(sent.get('headline_count', 0)))} analysed",
        f"  Bullish: {_escape_md(str(sent.get('bullish_count', 0)))} \\| Bearish: {_escape_md(str(sent.get('bearish_count', 0)))} \\| Neutral: {_escape_md(str(sent.get('neutral_count', 0)))}",
        f"  Sentiment Score: {_escape_md(str(sent.get('score', 'N/A')))}",
        "",
        f"⏰ {_escape_md(signal.timestamp)}",
        f"⚠️ _SIGNAL ONLY — No trades executed_",
    ]
    return "\n".join(lines)


def send_alert(signal, dry_run: bool = False) -> bool:
    """
    Send a signal alert to Telegram.

    Parameters
    ----------
    signal : Signal     from signal_engine
    dry_run : bool      if True, log the message but don't send

    Returns
    -------
    bool    True if sent (or logged in dry-run mode), False if skipped
    """
    symbol = signal.symbol

    # ── Secondary cooldown ───────────────────────────────────────────
    now = time.time()
    last = _last_notify_time.get(symbol, 0.0)
    if (now - last) < config.COOLDOWN_SECONDS:
        remaining = config.COOLDOWN_SECONDS - (now - last)
        logger.info(
            "Notifier cooldown active for %s — %.0fs remaining",
            symbol, remaining,
        )
        return False

    message = _format_alert(signal)

    # ── Dry-run mode ─────────────────────────────────────────────────
    if dry_run:
        logger.info("DRY RUN — would send alert:\n%s", message)
        _last_notify_time[symbol] = now
        return True

    # ── Send via Telegram Bot API ────────────────────────────────────
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram credentials not configured — skipping notification"
        )
        return False

    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("✅ Telegram alert sent for %s", symbol)
        _last_notify_time[symbol] = now
        return True

    except requests.RequestException as exc:
        logger.error("❌ Failed to send Telegram alert for %s: %s", symbol, exc)
        return False


# ── Trade Tracker Messages ───────────────────────────────────────────

def _progress_bar(percent: float, length: int = 10) -> str:
    """Create a text-based progress bar."""
    filled = max(0, min(length, int(percent / 100 * length)))
    bar = "█" * filled + "░" * (length - filled)
    return bar


def _format_trade_update(trade) -> str:
    """Build a periodic trade update message."""
    pnl = trade.pnl_percent
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    direction_emoji = "🟢" if trade.direction == "BUY" else "🔴"

    # Progress toward target (clamped 0-100)
    tp_progress = max(0, min(100, trade.distance_to_target_pct))
    tp_bar = _progress_bar(tp_progress)

    lines = [
        f"📊 *TRADE UPDATE* — {_escape_md(trade.symbol)}",
        "",
        f"*Direction:* {direction_emoji} {_escape_md(trade.direction)}",
        f"*Duration:* {_escape_md(trade.duration_str)}",
        f"*Update \\#{_escape_md(str(trade.update_count))}*",
        "",
        f"💰 *Price*",
        f"  Entry: {_escape_md(str(trade.entry_price))}",
        f"  Current: {_escape_md(f'{trade.current_price:.6f}')}",
        f"  Best: {_escape_md(f'{trade.peak_price:.6f}')}",
        "",
        f"{pnl_emoji} *P&L:* {_escape_md(f'{pnl:+.2f}')}% \\({_escape_md(f'{trade.pnl_absolute:+.6f}')}\\)",
        "",
        f"🎯 *To Target:* {_escape_md(f'{tp_progress:.1f}')}%",
        f"  {_escape_md(tp_bar)}",
        f"  🛑 SL: {_escape_md(str(trade.stop_loss))}",
        f"  🎯 TP: {_escape_md(str(trade.target))}",
        "",
        f"⚠️ _SIGNAL ONLY — No trades executed_",
    ]
    return "\n".join(lines)


def _format_trade_close(trade, event: str) -> str:
    """Build a trade-closed message (SL or TP hit)."""
    pnl = trade.pnl_percent

    if event == "target_hit":
        header = "🎯✅ *TARGET HIT*"
        result_emoji = "🏆"
        result_text = "PROFIT"
    else:
        header = "🛑❌ *STOP LOSS HIT*"
        result_emoji = "💔"
        result_text = "LOSS"

    direction_emoji = "🟢" if trade.direction == "BUY" else "🔴"

    lines = [
        f"{header} — {_escape_md(trade.symbol)}",
        "",
        f"{result_emoji} *Result:* {_escape_md(result_text)}",
        f"*Direction:* {direction_emoji} {_escape_md(trade.direction)}",
        f"*Duration:* {_escape_md(trade.duration_str)}",
        f"*Updates sent:* {_escape_md(str(trade.update_count))}",
        "",
        f"💵 *Final Numbers*",
        f"  Entry: {_escape_md(str(trade.entry_price))}",
        f"  Exit: {_escape_md(f'{trade.current_price:.6f}')}",
        f"  Best: {_escape_md(f'{trade.peak_price:.6f}')}",
        f"  Worst: {_escape_md(f'{trade.worst_price:.6f}')}",
        "",
        f"{'🟢' if pnl >= 0 else '🔴'} *Final P&L:* {_escape_md(f'{pnl:+.2f}')}%",
        "",
        f"⚠️ _SIGNAL ONLY — No trades executed_",
    ]
    return "\n".join(lines)


def send_trade_update(trade, event: str, dry_run: bool = False) -> bool:
    """
    Send a trade update or close notification to Telegram.

    Parameters
    ----------
    trade : ActiveTrade   from trade_tracker
    event : str           "update" | "target_hit" | "stop_loss_hit"
    dry_run : bool        if True, log instead of sending

    Returns
    -------
    bool    True if sent successfully
    """
    if event == "update":
        message = _format_trade_update(trade)
    else:
        message = _format_trade_close(trade, event)

    # ── Dry-run mode ─────────────────────────────────────────────────
    if dry_run:
        logger.info("DRY RUN — trade %s:\n%s", event, message)
        return True

    # ── Send via Telegram Bot API ────────────────────────────────────
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram credentials not configured — skipping trade update"
        )
        return False

    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("✅ Trade %s sent for %s", event, trade.symbol)
        return True

    except requests.RequestException as exc:
        logger.error(
            "❌ Failed to send trade %s for %s: %s", event, trade.symbol, exc
        )
        return False
