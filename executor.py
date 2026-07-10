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

        price = signal.entry_price
        
        # Calculate the raw amount
        raw_amount = config.POSITION_SIZE_USD / price
        
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
    
    # Clean up hard stops to avoid leaving ghost orders
    for oid in [trade.sl_order_id, trade.tp_order_id]:
        if oid:
            try:
                exchange.cancel_order(oid, trade.symbol)
                logger.info("Cleaned up hard stop/target order: %s", oid)
            except Exception:
                pass
                
    # If the exchange already closed it (Hard TP/SL hit), we don't need a market exit
    if not is_position_open(trade.symbol):
        logger.info("✅ Position already cleanly closed by exchange for %s.", trade.symbol)
        return True
        
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            price = trade.entry_price
            
            raw_amount = config.POSITION_SIZE_USD / price
            
            try:
                exchange.load_markets()
                amount = float(exchange.amount_to_precision(trade.symbol, raw_amount))
            except Exception:
                amount = raw_amount
            
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

def is_position_open(symbol: str) -> bool:
    """Checks if there's an active position for the symbol on the exchange."""
    if not config.AUTO_TRADE_ENABLED:
        return True  # Always assume open if paper trading
        
    try:
        exchange = _get_exchange()
        positions = exchange.fetch_positions([symbol])
        
        for p in positions:
            if p.get('symbol') == symbol and float(p.get('contracts', 0)) > 0:
                return True
                
        return False # Missing from exchange!
    except Exception as e:
        logger.warning("Could not verify position for %s: %s", symbol, e)
        return True # Default to true on API error so we don't falsely close real trades
