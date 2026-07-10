import time
import requests
import logging
import threading
from datetime import datetime, timezone

import config
import subscriber_manager
import report_tracker
import trade_tracker

logger = logging.getLogger(__name__)

_running = False

def _send_message(chat_id: int, text: str):
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = config.TELEGRAM_API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        logger.error("Failed to send message to %s: %s", chat_id, e)

def _send_welcome(chat_id: int):
    msg = (
        "🟢 *Welcome to Crypto Signal Bot!*\n\n"
        "You have been subscribed successfully.\n"
        "You will now receive live alerts and daily performance reports.\n\n"
        "Commands:\n"
        "/report — Get today's P&L and open trades\n"
        "/balance — Check your Binance Futures wallet\n"
        "/panic — 🛑 KILL SWITCH (Dump & Stop)\n"
        "/resume — ▶️ RESTART AUTO-TRADING\n"
        "/stop — Unsubscribe"
    )
    _send_message(chat_id, msg)

def _send_goodbye(chat_id: int):
    msg = (
        "🔴 *Unsubscribed!*\n\n"
        "You will no longer receive any alerts.\n"
        "Type /start to resubscribe."
    )
    _send_message(chat_id, msg)

def _send_pnl_report(chat_id: int):
    """Build and send today's P&L report to a single user."""
    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")

    # ── Section 1: Closed trades today ───────────────────────────────
    report = report_tracker.get_daily_report()
    closed_count = report.get("total_trades", 0)

    lines = [
        f"📊 *P&L Report — {date_str}*",
        "",
    ]

    if closed_count > 0:
        pnl_emoji = "🟢" if report["total_pnl"] >= 0 else "🔴"
        lines += [
            "*── Closed Trades ──*",
            f"  Total: {closed_count}",
            f"  ✅ Wins: {report['wins']}  |  🛑 Losses: {report['losses']}",
            f"  Win Rate: {report['win_rate']:.1f}%",
            f"  {pnl_emoji} Total P&L: {report['total_pnl']:+.2f}%",
            f"  Avg P&L/trade: {report['avg_pnl']:+.2f}%",
        ]
        best = report.get("best_trade")
        worst = report.get("worst_trade")
        if best:
            lines.append(f"  🏆 Best: {best['symbol']} {best['direction']} → {best['pnl_percent']:+.2f}%")
        if worst:
            lines.append(f"  💔 Worst: {worst['symbol']} {worst['direction']} → {worst['pnl_percent']:+.2f}%")

        lines.append("")
        lines.append("*Trade Log:*")
        for i, t in enumerate(report["trades"], 1):
            em = {"target_hit": "🎯", "stop_loss_hit": "🛑", "expired": "⏱️", "emergency_exit": "🚨"}.get(t["event"], "•")
            lines.append(f"  {i}. {em} {t['symbol']} {t['direction']} | {t['pnl_percent']:+.2f}% | {t['duration']}")
    else:
        lines.append("_No closed trades today._")

    # ── Section 2: Currently active trades ───────────────────────────
    portfolio = trade_tracker.get_portfolio_summary()
    active_count = portfolio.get("count", 0)

    lines.append("")
    if active_count > 0:
        lines += [
            f"*── Active Trades ({active_count}) ──*",
        ]
        for t in portfolio["trades"]:
            pnl_em = "🟢" if t["pnl_percent"] >= 0 else "🔴"
            lines.append(
                f"  {pnl_em} {t['symbol']} {t['direction']} | "
                f"P&L: {t['pnl_percent']:+.2f}% | {t['duration']} | "
                f"Target: {t['distance_to_target']:.0f}% away"
            )
        lines.append(f"  Avg unrealised P&L: {portfolio['avg_pnl']:+.2f}%")
    else:
        lines.append("_No active trades right now._")

    footer = "🤖 _TESTNET AUTO-TRADE EXECUTED_" if getattr(config, "AUTO_TRADE_ENABLED", False) else "⚠️ _SIGNAL ONLY — No real trades executed_"
    lines += ["", footer]

    _send_message(chat_id, "\n".join(lines))

def _poll_updates():
    offset = None
    # We must construct the getUpdates URL properly since config.TELEGRAM_API_URL 
    # might end with /sendMessage
    base_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
    url = f"{base_url}/getUpdates"
    
    while _running:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset

            resp = requests.get(url, params=params, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    for result in data.get("result", []):
                        update_id = result["update_id"]
                        offset = update_id + 1
                        
                        message = result.get("message")
                        if not message or "text" not in message or "chat" not in message:
                            continue
                        
                        text = message.get("text", "").strip()
                        chat_id = message.get("chat", {}).get("id")
                        
                        if not text or not chat_id:
                            continue
                            
                        if text.startswith("/start"):
                            is_new = subscriber_manager.add_subscriber(chat_id)
                            if is_new:
                                _send_welcome(chat_id)
                            else:
                                _send_message(chat_id, "You are already subscribed.")
                        elif text.startswith("/stop"):
                            is_removed = subscriber_manager.remove_subscriber(chat_id)
                            if is_removed:
                                _send_goodbye(chat_id)
                            else:
                                _send_message(chat_id, "You were not subscribed.")
                        elif text.startswith("/report"):
                            _send_pnl_report(chat_id)
                        elif text.startswith("/panic"):
                            _send_message(chat_id, "🚨 *PANIC SWITCH ACTIVATED*\nDisabling auto-trade and exiting all positions immediately!")
                            config.AUTO_TRADE_ENABLED = False
                            
                            active_trades = trade_tracker.get_active_trades()
                            closed = 0
                            for symbol, trade in active_trades.items():
                                import executor
                                # Temporarily re-enable auto-trade just to run the emergency exit function
                                config.AUTO_TRADE_ENABLED = True
                                success = executor.execute_exit(trade)
                                config.AUTO_TRADE_ENABLED = False
                                
                                if success:
                                    trade_tracker._active_trades.pop(symbol, None)
                                    trade_tracker._save_trades()
                                    closed += 1
                                    
                            _send_message(chat_id, f"✅ Successfully market-dumped {closed}/{len(active_trades)} positions. Auto-trading is now locked OFF.")
                            
                        elif text.startswith("/resume"):
                            config.AUTO_TRADE_ENABLED = True
                            _send_message(chat_id, "▶️ *AUTO-TRADE RESUMED*\n\nThe bot will now resume placing trades on Binance.")
                            
                        elif text.startswith("/balance"):
                            try:
                                import executor
                                exchange = executor._get_exchange()
                                bal = exchange.fetch_balance()
                                usdt = bal.get('USDT', {})
                                free = usdt.get('free', 0.0)
                                total = usdt.get('total', 0.0)
                                used = usdt.get('used', 0.0)
                                msg = (
                                    "💼 *BINANCE WALLET BALANCE*\n\n"
                                    f"💵 Total: `${total:.2f}`\n"
                                    f"🔓 Free Margin: `${free:.2f}`\n"
                                    f"🔒 In Trades: `${used:.2f}`"
                                )
                                _send_message(chat_id, msg)
                            except Exception as e:
                                _send_message(chat_id, "❌ Could not fetch balance. Check your API keys.")
                                logger.error("Balance fetch error: %s", e)
            
            time.sleep(1)
        except requests.exceptions.Timeout:
            pass  # Expected for long polling
        except requests.RequestException as e:
            logger.debug("Request exception in Telegram polling: %s", e)
            time.sleep(5)
        except Exception as e:
            logger.error("Error polling Telegram updates: %s", e)
            time.sleep(5)

def start_polling():
    global _running
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN, cannot start polling.")
        return
        
    subscriber_manager.load_subscribers()
    # Auto-add the admin chat id if present in config
    if config.TELEGRAM_CHAT_ID:
        try:
            admin_id = int(config.TELEGRAM_CHAT_ID)
            subscriber_manager.add_subscriber(admin_id)
        except ValueError:
            pass
            
    _running = True
    thread = threading.Thread(target=_poll_updates, daemon=True, name="BotListener")
    thread.start()
    logger.info("📡 Bot listener started, polling for /start commands.")

def stop_polling():
    global _running
    _running = False
