"""
Main Orchestrator — Wires all modules together in a polling loop.

Usage
-----
    python main.py                           # default watchlist
    python main.py --symbols BTC/USDT,SOL/USDT
    python main.py --dry-run                 # no Telegram, console only
    python main.py --interval 30             # poll every 30s
"""

import argparse
import logging
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime, timezone
import signal as os_signal
import sys
import time

def keep_alive():
    """Starts a dummy web server so Render doesn't shut us down."""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

import config
from data_pipeline import fetch_ohlcv, DataFetchError
from technicals import compute_technicals
from sentiment import fetch_sentiment, SentimentFetchError
from signal_engine import evaluate
from notifier import send_alert, send_trade_update, send_daily_report, send_startup_notification, send_heartbeat, _send_simple, _escape_md
from trade_tracker import register_trade, update_trades, get_active_trades, has_active_trade
import report_tracker
import bot_listener
import executor

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

# ── Graceful shutdown ────────────────────────────────────────────────
_running = True


def _shutdown_handler(signum, frame):
    global _running
    logger.info("Received shutdown signal (%s) — stopping after current cycle", signum)
    bot_listener.stop_polling()
    _running = False


os_signal.signal(os_signal.SIGINT, _shutdown_handler)
os_signal.signal(os_signal.SIGTERM, _shutdown_handler)


# ── Core scan ────────────────────────────────────────────────────────
def scan_symbol(symbol: str, dry_run: bool = False) -> None:
    """Run the full pipeline for a single symbol."""
    import datetime
    logger.info("━" * 50)
    logger.info("Scanning %s", symbol)
    
    # ── Session & Weekend Guards ─────────────────────────────────────
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if getattr(config, "AVOID_WEEKENDS", False) and now_utc.weekday() >= 5:
        logger.debug("Skipping %s — Weekend trading is disabled.", symbol)
        return
        
    allowed_hours = getattr(config, "ALLOWED_TRADING_HOURS_UTC", [])
    if allowed_hours and now_utc.hour not in allowed_hours:
        logger.debug("Skipping %s — Outside allowed UTC trading session.", symbol)
        return

    # Do not evaluate if there is already an active trade for this coin
    if has_active_trade(symbol):
        logger.info("Trade currently active for %s — waiting for it to close before generating new signals.", symbol)
        return

    # Max concurrent trades cap
    active_count = len(get_active_trades())
    if active_count >= config.MAX_CONCURRENT_TRADES:
        logger.info("Max concurrent trades (%d) reached — skipping new signal for %s",
                    config.MAX_CONCURRENT_TRADES, symbol)
        return

    # ── Daily Loss Circuit Breaker ───────────────────────────────────
    if report_tracker.is_circuit_breaker_active():
        logger.info("🚫 Circuit breaker active — skipping %s until daily reset.", symbol)
        return

    # 1 — Fetch Multi-Timeframe Candles
    try:
        df_5m = fetch_ohlcv(symbol, timeframe="5m", limit=100)
        df_15m = fetch_ohlcv(symbol, timeframe="15m", limit=100)
        df_1h = fetch_ohlcv(symbol, timeframe="1h", limit=250) # extra to cover 200 EMA
    except DataFetchError as exc:
        logger.error("Data pipeline failed for %s: %s", symbol, exc)
        return

    # 2 — Technicals (MTFA)
    try:
        tech = compute_technicals(df_5m, df_15m, df_1h)
    except Exception as exc:
        logger.error("Technical analysis failed for %s: %s", symbol, exc)
        return

    # 3 — Sentiment
    try:
        sent = fetch_sentiment(symbol)
    except SentimentFetchError as exc:
        logger.warning("Sentiment unavailable for %s: %s — using neutral", symbol, exc)
        sent = {"score": 50.0, "label": "Neutral", "headline_count": 0,
                "headlines": [], "bullish_count": 0, "bearish_count": 0,
                "neutral_count": 0}

    # 4 — Decision
    sig = evaluate(symbol, tech, sent)

    if sig is None:
        logger.info("No actionable signal for %s", symbol)
        return

    # 5 — Notify (PENDING signal — trade not yet confirmed)
    sent_ok = send_alert(sig, dry_run=dry_run)
    if not sent_ok and not dry_run:
        logger.warning("Alert for %s was not delivered", symbol)

    # 6 — Signal Confirmation Delay (wait and re-validate before executing)
    if not dry_run and getattr(config, "AUTO_TRADE_ENABLED", False):
        delay = getattr(config, "SIGNAL_CONFIRMATION_DELAY", 50)
        tolerance = getattr(config, "ENTRY_PRICE_TOLERANCE_PCT", 0.15)
        
        logger.info("⏳ CONFIRMATION WAIT: Holding %s signal for %ds before executing...", symbol, delay)
        _send_simple(
            f"⏳ *CONFIRMING SIGNAL*\n\n"
            f"Waiting {delay}s to verify {_escape_md(sig.direction)} {_escape_md(symbol)} "
            f"near entry zone `{_escape_md(f'${sig.entry_price:,.2f}')}`\\.\\.\\.",
            dry_run=dry_run
        )
        
        # Wait in small increments so we can abort on shutdown
        for _ in range(delay):
            if not _running:
                return
            time.sleep(1)
        
        # Re-fetch the LIVE price after waiting
        from data_pipeline import fetch_live_prices
        fresh_prices = fetch_live_prices([symbol])
        live_price = fresh_prices.get(symbol)
        
        if live_price is None:
            logger.error("Could not fetch confirmation price for %s. Aborting trade.", symbol)
            _send_simple(f"❌ *SIGNAL CANCELLED*\n\nCould not verify price for {_escape_md(symbol)}\\.", dry_run=dry_run)
            return
        
        # Calculate how much the price drifted AGAINST us
        drift_pct = ((live_price - sig.entry_price) / sig.entry_price) * 100
        
        # For BUY: price dropping too far is bad (negative drift)
        # For SELL: price rising too far is bad (positive drift)
        if sig.direction == "BUY" and drift_pct < -tolerance:
            logger.warning("❌ BUY signal CANCELLED for %s: Price dropped %.2f%% (%.2f → %.2f)", 
                          symbol, abs(drift_pct), sig.entry_price, live_price)
            _send_simple(
                f"❌ *SIGNAL CANCELLED — FAKE\\-OUT DETECTED*\n\n"
                f"{_escape_md(symbol)} price dropped `{_escape_md(f'{abs(drift_pct):.2f}')}%` "
                f"during confirmation\\. Trade aborted\\.",
                dry_run=dry_run
            )
            return
        elif sig.direction == "SELL" and drift_pct > tolerance:
            logger.warning("❌ SELL signal CANCELLED for %s: Price rose %.2f%% (%.2f → %.2f)",
                          symbol, drift_pct, sig.entry_price, live_price)
            _send_simple(
                f"❌ *SIGNAL CANCELLED — FAKE\\-OUT DETECTED*\n\n"
                f"{_escape_md(symbol)} price rose `{_escape_md(f'{drift_pct:.2f}')}%` "
                f"during confirmation\\. Trade aborted\\.",
                dry_run=dry_run
            )
            return
        
        # CONFIRMED — Price held or moved in our favour!
        logger.info("✅ Signal CONFIRMED for %s! Price drift: %+.2f%% (within %.2f%% tolerance)", 
                    symbol, drift_pct, tolerance)
        _send_simple(
            f"✅ *SIGNAL CONFIRMED*\n\n"
            f"Price held steady\\. Executing {_escape_md(sig.direction)} on {_escape_md(symbol)} now\\!",
            dry_run=dry_run
        )
        
        exec_result = executor.execute_entry(sig)
        if not exec_result["success"]:
            logger.error("Auto-trade execution failed for %s. Discarding signal.", symbol)
            _send_simple(f"❌ *AUTO\\-TRADE FAILED*\n\nThe scheduled {_escape_md(sig.direction)} trade for {_escape_md(symbol)} could not be opened on Binance\\. Discarding signal\\.", dry_run=dry_run)
            return
            
        # Update the tracked entry price to precisely match Binance's fill price
        fill_price = exec_result["avg_price"]
        if fill_price > 0:
            sig.entry_price = fill_price
            
        sig.amount = exec_result["amount"]
        sig.sl_order_id = exec_result["sl_id"]
        sig.tp_order_id = exec_result["tp_id"]

    # 7 — Register trade for tracking
    register_trade(sig)
    logger.info("Trade registered for continuous tracking: %s", symbol)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crypto Signal Generator — signal-only, no trade execution"
    )
    parser.add_argument(
        "--symbols",
        type=lambda s: [x.strip() for x in s.split(",")],
        default=config.SYMBOLS,
        help="Comma-separated trading pairs (default: from config)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=config.POLL_INTERVAL,
        help="Seconds between scan cycles (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print alerts to console instead of sending to Telegram",
    )
    args = parser.parse_args()

    # Start dummy web server for Render's Web Service plan
    keep_alive()
    
    # Listen for new Telegram subscribers
    if not args.dry_run:
        bot_listener.start_polling()

    symbols = args.symbols
    interval = args.interval
    dry_run = args.dry_run

    # Send startup notification (now that symbols/interval/dry_run are defined)
    send_startup_notification(symbols, interval, dry_run=dry_run)

    logger.info("=" * 60)
    logger.info("CRYPTO SIGNAL GENERATOR")
    logger.info("=" * 60)
    logger.info("Symbols  : %s", ", ".join(symbols))
    logger.info("Interval : %ds", interval)
    logger.info("Dry run  : %s", dry_run)
    logger.info("Threshold: %.0f%%", config.CONFIDENCE_THRESHOLD * 100)
    logger.info("Cooldown : %ds", config.COOLDOWN_SECONDS)
    logger.info("Weights  : tech=%.0f%% / sent=%.0f%%",
                config.TECHNICAL_WEIGHT * 100, config.SENTIMENT_WEIGHT * 100)
    logger.info("=" * 60)

    cycle = 0
    _last_report_day: int = -1
    _last_heartbeat_hour: int = -1  # track which UTC-hour we last sent a heartbeat
    while _running:
        cycle += 1
        logger.info("── Cycle %d ──", cycle)

        for symbol in symbols:
            if not _running:
                break
            scan_symbol(symbol, dry_run=dry_run)

        # ── Track active trades ──────────────────────────────────────
        active = get_active_trades()
        if active:
            logger.info("📋 Tracking %d active trade(s): %s",
                        len(active), ", ".join(active.keys()))
            trade_updates = update_trades(dry_run=dry_run)
            for upd in trade_updates:
                event = upd["event"]
                trade = upd["trade"]
                
                send_trade_update(trade, event, dry_run=dry_run)
                
                if not dry_run and event in ["target_hit", "stop_loss_hit", "expired", "emergency_exit"]:
                    executor.execute_exit(trade)

        # ── Heartbeat ───────────────────────────────────────────────
        now_utc = datetime.now(timezone.utc)
        heartbeat_slot = now_utc.hour // config.HEARTBEAT_INTERVAL_HOURS
        if heartbeat_slot != _last_heartbeat_hour:
            active = get_active_trades()
            send_heartbeat(len(active), dry_run=dry_run)
            _last_heartbeat_hour = heartbeat_slot

        # ── Daily Report Check ───────────────────────────────────────
        if now_utc.hour == config.DAILY_REPORT_HOUR and now_utc.day != _last_report_day:
            logger.info("📅 Sending daily report...")
            daily = report_tracker.get_daily_report()
            send_daily_report(daily, dry_run=dry_run)
            report_tracker.reset_daily_report()
            _last_report_day = now_utc.day

        if _running:
            logger.info("Sleeping %ds until next cycle…", interval)
            # Sleep in small increments so shutdown is responsive
            for _ in range(interval):
                if not _running:
                    break
                time.sleep(1)

    logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
