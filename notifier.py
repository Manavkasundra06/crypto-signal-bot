"""
Notifier — Sends formatted signal alerts to Telegram.

Uses the Telegram Bot API (`sendMessage` with MarkdownV2 parse mode).
Includes a secondary cooldown check as a safety net.
"""

import time
import logging

import requests

import config
import subscriber_manager

logger = logging.getLogger(__name__)

def _get_footer() -> str:
    if getattr(config, "AUTO_TRADE_ENABLED", False):
        return "🤖 _TESTNET AUTO\\-TRADE EXECUTED_"
    return "⚠️ _SIGNAL ONLY — No trades executed_"

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
    margin_usd = (signal.amount * signal.entry_price) / config.LEVERAGE
    margin_inr = margin_usd * config.USD_INR_RATE
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
        f"\U0001f4b0 *Trade Execution*",
        f"  Leverage: {_escape_md(str(config.LEVERAGE))}x",
        f"  Investment: ${_escape_md(f'{margin_usd:.2f}')} \(₹{_escape_md(f'{margin_inr:.2f}')}\)",
        "",
        f"💵 *Price Levels*",
        f"  Entry Price: {_escape_md(str(signal.entry_price))}",
        f"  🛑 Stop Loss: {_escape_md(str(signal.stop_loss))}",
        f"  🎯 Target: {_escape_md(str(signal.target))}",
        "",
        f"📊 *Technicals* \\({_escape_md(str(int(config.TECHNICAL_WEIGHT * 100)))}% weight\\)",
        f"  RSI\\(14\\): {_escape_md(str(tech.get('rsi', 'N/A')))} → {_escape_md(str(tech.get('bias', 'N/A')))} \\(Score: {_escape_md(str(tech.get('rsi_score', 'N/A')))}\\)",
        f"  Volume: {_escape_md(str(tech.get('volume_ratio', 'N/A')))}x avg \\(Score: {_escape_md(str(tech.get('volume_score', 'N/A')))}\\)",
        f"  Momentum \\(15m MACD\\): {_escape_md(str(tech.get('momentum_score', 'N/A')))}",
        f"  Trend \\(1h EMA\\): {_escape_md(str(tech.get('trend_score', 'N/A')))}",
        f"  Tech Score: {_escape_md(str(tech.get('composite_score', 'N/A')))}",
        "",
        f"📰 *Sentiment* \\({_escape_md(str(int(config.SENTIMENT_WEIGHT * 100)))}% weight\\)",
        f"  Headlines: {_escape_md(str(sent.get('headline_count', 0)))} analysed",
        f"  Bullish: {_escape_md(str(sent.get('bullish_count', 0)))} \\| Bearish: {_escape_md(str(sent.get('bearish_count', 0)))} \\| Neutral: {_escape_md(str(sent.get('neutral_count', 0)))}",
        f"  Sentiment Score: {_escape_md(str(sent.get('score', 'N/A')))}",
        "",
        f"⏰ {_escape_md(signal.timestamp)}",
        _get_footer(),
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
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram Bot Token not configured — skipping notification")
        return False

    subs = subscriber_manager.get_subscribers()
    if not subs:
        logger.warning("No subscribers to notify for %s", symbol)
        return False

    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    success = False

    for chat_id in subs:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            success = True
        except requests.RequestException as exc:
            logger.error("❌ Failed to send Telegram alert to %s for %s: %s", chat_id, symbol, exc)

    if success:
        logger.info("✅ Telegram alert sent for %s", symbol)
        _last_notify_time[symbol] = now

    return success


# ── Trade Tracker Messages ───────────────────────────────────────────

def _progress_bar(percent: float, length: int = 10) -> str:
    """Create a text-based progress bar."""
    filled = max(0, min(length, int(percent / 100 * length)))
    bar = "█" * filled + "░" * (length - filled)
    return bar


def _format_trade_update(trade) -> str:
    """Build a periodic trade update message."""
    pnl = trade.pnl_percent
    pnl_emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
    direction_emoji = "\U0001f7e2" if trade.direction == "BUY" else "\U0001f534"
    
    tp_progress = max(0, min(100, trade.distance_to_target_pct))
    tp_bar = _progress_bar(tp_progress)
    
    inr_val = trade.pnl_usd * getattr(config, 'USD_INR_RATE', 83.5)
    
    lines = [
        f"\U0001f4ca *TRADE UPDATE* — {_escape_md(trade.symbol)}",
        "",
        f"*Direction:* {direction_emoji} {_escape_md(trade.direction)}",
        f"*Duration:* {_escape_md(trade.duration_str)}",
        f"*Update \#{_escape_md(str(trade.update_count))}*",
        "",
        f"\U0001f4b8 *Price*",
        f"  Entry: {_escape_md(str(trade.entry_price))}",
        f"  Current: {_escape_md(f'{trade.current_price:.6f}')}",
        f"  Best: {_escape_md(f'{trade.peak_price:.6f}')}",
        "",
        f"{pnl_emoji} *P&L:* {_escape_md(f'{pnl:+.2f}')}% \(Net: *\${_escape_md(f'{trade.pnl_usd:+.2f}')}* \| ₹{_escape_md(f'{inr_val:+.2f}')}\)",
        f"  {tp_bar} {_escape_md(f'{tp_progress:.1f}')}% to TP",
        "",
        _get_footer(),
    ]
    return "\n".join(lines)

def _format_trade_close(trade, event: str) -> str:
    """Build a trade-closed message (SL or TP hit)."""
    pnl = trade.pnl_percent
    
    if event == "target_hit":
        header = "\U0001f3af\U0001f4b0 *TARGET HIT*"
        result_emoji = "\U0001f680"
        result_text = "PROFIT"
    elif event == "stop_loss_hit":
        if pnl > 0:
            header = "\U0001f6a8\U0001f4c8 *TRAILING STOP HIT*"
            result_emoji = "\U0001f4b8"
            result_text = "SECURED PROFIT"
        else:
            header = "\U0001f6a8\u26d4 *STOP LOSS HIT*"
            result_emoji = "\U0001f4a5"
            result_text = "LOSS"
    elif event == "emergency_exit":
        header = "\U0001f6a8\U0001f4f0 *NEWS EMERGENCY EXIT*"
        result_emoji = "\U0001f6a8"
        result_text = "MARKET FLIPPED"
    else:
        header = "\u23f1\ufe0f *TRADE EXPIRED*"
        result_emoji = "\u23f1\ufe0f"
        result_text = "TIME LIMIT REACHED"
        
    inr_val = trade.pnl_usd * getattr(config, 'USD_INR_RATE', 83.5)
    pnl_emoji = "\U0001f7e2" if pnl >= 0 else "\U0001f534"
        
    lines = [
        f"{header} — {_escape_md(trade.symbol)}",
        "",
        f"*{result_text}* {result_emoji}",
        f"Direction: {_escape_md(trade.direction)}",
        f"Duration: {_escape_md(trade.duration_str)}",
        "",
        f"\U0001f4b8 Entry: {_escape_md(str(trade.entry_price))}",
        f"\U0001f4b8 Exit: {_escape_md(str(trade.current_price))}",
        "",
        f"{pnl_emoji} *Final P&L:* {_escape_md(f'{pnl:+.2f}')}% \(Net: *\${_escape_md(f'{trade.pnl_usd:+.2f}')}* \| ₹{_escape_md(f'{inr_val:+.2f}')}\)",
        "",
        _get_footer(),
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
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram credentials not configured — skipping trade update")
        return False

    subs = subscriber_manager.get_subscribers()
    if not subs:
        return False

    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    success = False

    for chat_id in subs:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            success = True
        except requests.RequestException as exc:
            logger.error("❌ Failed to send trade %s to %s for %s: %s", event, chat_id, trade.symbol, exc)

    if success:
        logger.info("✅ Trade %s sent for %s", event, trade.symbol)

    return success


# ── Startup & Heartbeat Notifications ────────────────────────────────

def _send_simple(message: str, dry_run: bool = False) -> bool:
    """Internal helper to send a plain message."""
    if dry_run:
        logger.info("DRY RUN — message:\n%s", message)
        return True
    if not config.TELEGRAM_BOT_TOKEN:
        return False
        
    subs = subscriber_manager.get_subscribers()
    if not subs:
        return False

    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    success = False
    
    for chat_id in subs:
        try:
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "MarkdownV2",
            }, timeout=10)
            resp.raise_for_status()
            success = True
        except requests.RequestException as exc:
            logger.error("Failed to send message to %s: %s", chat_id, exc)
            
    return success


def send_startup_notification(symbols: list, interval: int, dry_run: bool = False) -> bool:
    """Send a Telegram message when the bot starts up."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sym_list = _escape_md(", ".join(symbols))
    msg = (
        f"🟢 *CRYPTO SIGNAL BOT STARTED*\n\n"
        f"📅 Started at: {_escape_md(now)}\n"
        f"📊 Watching: {sym_list}\n"
        f"⏱️ Scan interval: {_escape_md(str(interval))}s\n"
        f"🔄 Multi\\-timeframe: 5m \\+ 15m \\+ 1h\n\n"
        f"_Bot is live and monitoring markets\\._"
    )
    logger.info("📡 Sending startup notification...")
    return _send_simple(msg, dry_run=dry_run)


def send_heartbeat(active_trades: int, dry_run: bool = False) -> bool:
    """Send a periodic heartbeat ping so you know the bot is alive."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    msg = (
        f"💓 *BOT HEARTBEAT*\n\n"
        f"🕐 {_escape_md(now)}\n"
        f"📋 Active trades: {_escape_md(str(active_trades))}\n"
        f"_All systems running normally\\._"
    )
    logger.info("💓 Sending heartbeat...")
    return _send_simple(msg, dry_run=dry_run)


# ── Daily Report ──────────────────────────────────────────────────────

def _format_daily_report(report: dict) -> str:
    """Build the end-of-day performance report message."""
    if report.get("total_trades", 0) == 0:
        date_str = _escape_md(report.get("date", "N/A"))
        return f"📅 *DAILY REPORT — {date_str}*\n\nNo trades were completed today\\."

    def outcome_emoji(event: str) -> str:
        return {"target_hit": "🎯", "stop_loss_hit": "🛑", "expired": "⏱️", "emergency_exit": "🚨"}.get(event, "•")

    pnl_total    = report["total_pnl"]
    avg_pnl      = report["avg_pnl"]
    win_rate     = report["win_rate"]
    total_trades = report["total_trades"]
    wins         = report["wins"]
    losses       = report["losses"]
    expired      = report["expired"]
    emergency    = report["emergency_exits"]
    date         = report["date"]
    best         = report.get("best_trade")
    worst        = report.get("worst_trade")

    pnl_emoji    = "🟢" if pnl_total >= 0 else "🔴"
    win_bar_n    = max(0, min(10, round(win_rate / 10)))
    win_bar      = "█" * win_bar_n + "░" * (10 - win_bar_n)

    total_pnl_s  = _escape_md(f"{pnl_total:+.2f}")
    avg_pnl_s    = _escape_md(f"{avg_pnl:+.2f}")
    win_rate_s   = _escape_md(f"{win_rate:.1f}")
    win_bar_s    = _escape_md(win_bar)

    lines = [
        f"📅 *DAILY REPORT — {_escape_md(date)}*",
        "",
        "📊 *Performance Summary*",
        f"  Total Signals: *{_escape_md(str(total_trades))}*",
        f"  ✅ Target Hit: {_escape_md(str(wins))}  🛑 SL Hit: {_escape_md(str(losses))}  ⏱️ Expired: {_escape_md(str(expired))}  🚨 Emergency: {_escape_md(str(emergency))}",
        f"  Win Rate: {win_rate_s}%  {win_bar_s}",
        "",
        f"{pnl_emoji} *P&L Summary*",
        f"  Total P&L: {total_pnl_s}%",
        f"  Average P&L per trade: {avg_pnl_s}%",
    ]

    if best:
        b_pnl = _escape_md(f"{best['pnl_percent']:+.2f}")
        b_sym = _escape_md(best["symbol"])
        b_dir = _escape_md(best["direction"])
        lines += ["", f"🏆 *Best Trade:* {b_sym} {b_dir} \\→ {b_pnl}%"]
    if worst:
        w_pnl = _escape_md(f"{worst['pnl_percent']:+.2f}")
        w_sym = _escape_md(worst["symbol"])
        w_dir = _escape_md(worst["direction"])
        lines += [f"💔 *Worst Trade:* {w_sym} {w_dir} \\→ {w_pnl}%"]

    lines += ["", "📋 *Trade Log*"]
    for i, t in enumerate(report["trades"], 1):
        em    = outcome_emoji(t["event"])
        p_str = _escape_md(f"{t['pnl_percent']:+.2f}")
        dur   = _escape_md(t["duration"])
        sym   = _escape_md(t["symbol"])
        dire  = _escape_md(t["direction"])
        lines.append(f"  {i}\\. {em} {sym} {dire} \\| P&L: {p_str}% \\| {dur}")

    lines += ["", _get_footer()]
    return "\n".join(lines)


def send_daily_report(report: dict, dry_run: bool = False) -> bool:
    """
    Send the end-of-day performance report to Telegram.

    Parameters
    ----------
    report : dict     from report_tracker.get_daily_report()
    dry_run : bool    if True, log to console only
    """
    message = _format_daily_report(report)

    if dry_run:
        logger.info("DRY RUN — Daily Report:\n%s", message)
        return True

    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram credentials not configured — skipping daily report")
        return False

    subs = subscriber_manager.get_subscribers()
    if not subs:
        return False

    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    success = False
    
    for chat_id in subs:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            success = True
        except requests.RequestException as exc:
            logger.error("❌ Failed to send daily report to %s: %s", chat_id, exc)
            
    if success:
        logger.info("✅ Daily report sent.")
        
    return success
