import logging
import config
from data_pipeline import _get_exchange

logger = logging.getLogger(__name__)

def execute_entry(signal) -> dict:
    """Executes a real order on the exchange and places Hard Stops if AUTO_TRADE is enabled."""
    if not config.AUTO_TRADE_ENABLED:
        return {"success": False, "avg_price": 0.0, "amount": 0.0, "sl_id": "", "tp_id": ""}
        
    try:
        exchange = _get_exchange()
        
        try:
            exchange.set_margin_mode('isolated', signal.symbol)
            logger.info("Set margin mode to ISOLATED for %s", signal.symbol)
        except Exception as e:
            logger.warning("Could not set ISOLATED margin for %s (may already be isolated or unsupported): %s", signal.symbol, e)
            
        try:
            exchange.set_leverage(config.LEVERAGE, signal.symbol)
            logger.info("Set leverage to %sx for %s", config.LEVERAGE, signal.symbol)
        except Exception as e:
            logger.warning("Could not set leverage to %s for %s. It might already be set: %s", config.LEVERAGE, signal.symbol, e)

        # ── DUPLICATE ENTRY GUARD ────────────────────────────────────
        # If the exchange already has a live position for this symbol, ABORT.
        # This prevents re-entering after a false ghost-trade purge.
        if is_position_open(signal.symbol):
            logger.warning("⚠️ DUPLICATE ENTRY BLOCKED: %s already has an open position on Binance!", signal.symbol)
            return {"success": False, "avg_price": 0, "amount": 0, "sl_id": "", "tp_id": ""}

        price = signal.entry_price
        
        # ── DYNAMIC POSITION SIZING ──────────────────────────────────
        target_notional_usd = config.POSITION_SIZE_USD
        if getattr(config, "DYNAMIC_SIZING_ENABLED", False):
            try:
                balance = exchange.fetch_balance()
                free_usdt = balance.get('USDT', {}).get('free', 0.0)
                if free_usdt > 0:
                    # e.g., 10% risk of $10 free balance = $1 margin per trade
                    margin_per_trade = free_usdt * (config.RISK_PER_TRADE_PCT / 100.0)
                    target_notional_usd = margin_per_trade * config.LEVERAGE
                    logger.info("💰 Dynamic Sizing: Using $%.2f margin (%.1f%% of $%.2f free USDT) -> $%.2f notional",
                                margin_per_trade, config.RISK_PER_TRADE_PCT, free_usdt, target_notional_usd)
            except Exception as e:
                logger.warning("Could not fetch balance for dynamic sizing — falling back to $%.2f notional: %s", 
                               target_notional_usd, e)
                               
        # Calculate the raw amount
        raw_amount = target_notional_usd / price
        
        try:
            exchange.load_markets()
            # Format amount to the exchange's required precision step (e.g., 0.001 for BTC)
            amount = float(exchange.amount_to_precision(signal.symbol, raw_amount))
        except Exception:
            amount = raw_amount
        
        side = 'buy' if signal.direction == 'BUY' else 'sell'
        
        logger.info("🚀 EXECUTING TESTNET ENTRY: %s %.6f %s", side.upper(), amount, signal.symbol)
        
        order = exchange.create_market_order(signal.symbol, side, amount)
        avg_price = order.get('average') or order.get('price') or price
        logger.info("✅ Entry Order Filled! ID: %s | Avg Price: %s", order.get('id', 'N/A'), avg_price)
        
        # ── EXACT SLIPPAGE ALIGNMENT FOR HARD STOPS ─────────────
        # Wicks/slippage can cause the real entry price to differ from the tested price.
        # We MUST shift the Target and Stop Loss precisely to match the real entry!
        avg_price_flt = float(avg_price)
        if signal.direction == 'BUY':
            sl_dist = signal.entry_price - signal.stop_loss
            tp_dist = signal.target - signal.entry_price
            
            signal.stop_loss = round(avg_price_flt - sl_dist, 6)
            signal.target = round(avg_price_flt + tp_dist, 6)
        else:
            sl_dist = signal.stop_loss - signal.entry_price
            tp_dist = signal.entry_price - signal.target
            
            signal.stop_loss = round(avg_price_flt + sl_dist, 6)
            signal.target = round(avg_price_flt - tp_dist, 6)
            
        inverse_side = 'sell' if side == 'buy' else 'buy'
        sl_id = ""
        tp_id = ""
        
        try:
            # Note: Binance Futures uses stopPrice for both STOP_MARKET and TAKE_PROFIT_MARKET
            sl_order = exchange.create_order(
                signal.symbol, 'STOP_MARKET', inverse_side, amount, 
                params={'stopPrice': signal.stop_loss, 'reduceOnly': True}
            )
            sl_id = sl_order.get('id', '')
            logger.info("🛡️ Hard Stop-Loss Placed on Exchange: %s", signal.stop_loss)
            
            if getattr(config, "PARTIAL_TP_ENABLED", False):
                # Calculate Partial TP thresholds
                # Distance from real fill to final target
                tp_dist = signal.target - avg_price_flt if signal.direction == 'BUY' else avg_price_flt - signal.target
                partial_tp_dist = tp_dist * (config.PARTIAL_TP_TRIGGER_PCT / 100.0)
                
                partial_tp_price = avg_price_flt + partial_tp_dist if signal.direction == 'BUY' else avg_price_flt - partial_tp_dist
                partial_amount = float(exchange.amount_to_precision(signal.symbol, amount * (config.PARTIAL_TP_CLOSE_PCT / 100.0)))
                final_amount = float(exchange.amount_to_precision(signal.symbol, amount - partial_amount))
                
                # 1) Partial TP
                if partial_amount > 0:
                    exchange.create_order(
                        signal.symbol, 'TAKE_PROFIT_MARKET', inverse_side, partial_amount, 
                        params={'stopPrice': round(partial_tp_price, 6), 'reduceOnly': True}
                    )
                    logger.info("🎯 Partial TP Placed: %.6f for %s contracts", partial_tp_price, partial_amount)
                
                # 2) Final TP
                if final_amount > 0:
                    tp_order = exchange.create_order(
                        signal.symbol, 'TAKE_PROFIT_MARKET', inverse_side, final_amount, 
                        params={'stopPrice': round(signal.target, 6), 'reduceOnly': True}
                    )
                    tp_id = tp_order.get('id', '')
                    logger.info("🎯 Final TP Placed on Exchange: %s for %s contracts", signal.target, final_amount)
            else:
                tp_order = exchange.create_order(
                    signal.symbol, 'TAKE_PROFIT_MARKET', inverse_side, amount, 
                    params={'stopPrice': signal.target, 'reduceOnly': True}
                )
                tp_id = tp_order.get('id', '')
                logger.info("🎯 Hard Take-Profit Placed on Exchange: %s", signal.target)
        except Exception as e:
            logger.error("⚠️ Failed to place hard SL/TP orders: %s. You may be naked on this trade!", e)
            
        return {
            "success": True, 
            "avg_price": avg_price_flt,
            "amount": float(amount),
            "sl_id": sl_id,
            "tp_id": tp_id
        }
    except Exception as e:
        logger.error("❌ Failed to execute entry order: %s", e)
        return {"success": False, "avg_price": 0.0, "amount": 0.0, "sl_id": "", "tp_id": ""}
        
def move_hard_stop(symbol: str, old_sl_id: str, new_sl_price: float, side: str, amount: float) -> str:
    """Cancels the old Stop Loss on Binance and places a new trailing one."""
    if not config.AUTO_TRADE_ENABLED:
        return ""
        
    exchange = _get_exchange()
    try:
        if old_sl_id:
            exchange.cancel_order(old_sl_id, symbol)
            logger.info("Canceled old hard stop %s", old_sl_id)
    except Exception as e:
        logger.warning("Failed to cancel old SL order %s: %s", old_sl_id, e)
        
    try:
        new_order = exchange.create_order(
            symbol, 'STOP_MARKET', side, amount, 
            params={'stopPrice': new_sl_price, 'reduceOnly': True}
        )
        logger.info("🛡️ Trailing Hard Stop moved to: %s", new_sl_price)
        return new_order.get('id', '')
    except Exception as e:
        logger.error("❌ Failed to place new trailing hard stop: %s", e)
        return old_sl_id

def execute_exit(trade) -> bool:
    """Closes an active position if AUTO_TRADE is enabled, with built-in retries."""
    import time
    if not config.AUTO_TRADE_ENABLED:
        return False
        
    exchange = _get_exchange()
    
    # Clean up ALL open target/stop limit orders linked to this pair
    try:
        exchange.cancel_all_orders(trade.symbol)
        logger.info("🧹 Cleaned up all resting ghost orders for %s", trade.symbol)
    except Exception as exc:
        logger.warning("Could not cleanly bulk-cancel orders for %s: %s", trade.symbol, exc)
                
    # If the exchange already closed it (Hard TP/SL hit), we don't need a market exit
    if not is_position_open(trade.symbol):
        logger.info("✅ Position already cleanly closed by exchange for %s.", trade.symbol)
        return True
        
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            price = trade.entry_price
            
            # Safely close exactly the amount we opened
            amount = trade.amount
            
            # Inverse the direction to close the trade
            side = 'sell' if trade.direction == 'BUY' else 'buy'
            
            logger.info("🛑 EXECUTING TESTNET CLOSE (Attempt %d/%d): %s %.6f %s", attempt, config.MAX_RETRIES, side.upper(), amount, trade.symbol)
            
            order = exchange.create_market_order(trade.symbol, side, amount, params={'reduceOnly': True})
            logger.info("✅ Close Order Filled! ID: %s", order.get('id', 'N/A'))
            return True
            
        except Exception as e:
            wait = config.RETRY_BACKOFF_BASE ** attempt
            logger.warning("❌ Failed close order for %s: %s — retrying in %.1fs", trade.symbol, e, wait)
            time.sleep(wait)
            
    logger.error("🚨 CRITICAL: Completely failed to close %s after %d retries! Position may still be open on Binance!", trade.symbol, config.MAX_RETRIES)
    return False

_api_failure_counts: dict[str, int] = {}

def is_position_open(symbol: str) -> bool:
    """Checks if there's an active position for the symbol on the exchange, with API resilience and dust filtering."""
    if not config.AUTO_TRADE_ENABLED:
        return True
        
    try:
        exchange = _get_exchange()
        positions = exchange.fetch_positions([symbol])
        
        _api_failure_counts[symbol] = 0
        
        for p in positions:
            p_symbol = p.get('symbol', '')
            if symbol.split('/')[0] in p_symbol:
                contracts = float(p.get('contracts', 0))
                notional = float(p.get('notional', 0))
                
                if notional == 0 and contracts > 0:
                    price = float(p.get('markPrice') or p.get('entryPrice') or 0.0)
                    notional = contracts * price
                
                dust_threshold = getattr(config, "DUST_NOTIONAL_THRESHOLD", 1.0)
                if contracts > 0 and notional >= dust_threshold:
                    return True
                elif contracts > 0:
                    logger.info("Ignoring Dust Position for %s: %s contracts, $%.2f notional", symbol, contracts, notional)
                
        return False
        
    except Exception as e:
        failures = _api_failure_counts.get(symbol, 0) + 1
        _api_failure_counts[symbol] = failures
        max_failures = getattr(config, "MAX_API_FAILURES", 5)
        
        if failures >= max_failures:
            logger.error("dYs API Sync Override: %s failed %d consecutive times. Forcing trade closed to prevent Zombie state!", symbol, failures)
            _api_failure_counts[symbol] = 0
            return False
            
        logger.warning("Could not verify position for %s (Attempt %d/%d): %s", symbol, failures, max_failures, e)
        return True


def update_stop_loss(trade, new_sl_price: float) -> bool:
    """Cancels the old SL and places a new one at Breakeven/Trailing."""
    if not config.AUTO_TRADE_ENABLED:
        return False
    try:
        exchange = _get_exchange()
        
        # Cancel old SL
        if trade.sl_order_id:
            try:
                exchange.cancel_order(trade.sl_order_id, trade.symbol)
                logger.info("Cancelled old SL for %s", trade.symbol)
            except Exception as e:
                logger.warning("Could not cancel old SL %s: %s", trade.sl_order_id, e)
                
        # Place new SL
        side = "sell" if trade.direction == "BUY" else "buy"
        params = {
            'stopPrice': float(new_sl_price),
            'reduceOnly': True,
            'workingType': 'MARK_PRICE'
        }
        
        # Load markets for precision formatting
        exchange.load_markets()
        market = exchange.market(trade.symbol)
        amount_fmt = float(exchange.amount_to_precision(trade.symbol, trade.amount))
        sl_fmt = float(exchange.price_to_precision(trade.symbol, new_sl_price))
        
        sl_order = exchange.create_order(
            symbol=trade.symbol,
            type='STOP_MARKET',
            side=side,
            amount=amount_fmt,
            price=None,
            params=params
        )
        
        if sl_order and 'id' in sl_order:
            trade.sl_order_id = str(sl_order['id'])
            trade.stop_loss = sl_fmt
            logger.info("dY>` Moved SL for %s to %.6f", trade.symbol, sl_fmt)
            return True
            
    except Exception as exc:
        logger.error("Failed to update SL for %s: %s", trade.symbol, exc)
        return False
        
    return False
