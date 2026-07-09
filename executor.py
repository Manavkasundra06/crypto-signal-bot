import logging
import config
from data_pipeline import _get_exchange

logger = logging.getLogger(__name__)

def execute_entry(signal) -> bool:
    """Executes a real order on the exchange if AUTO_TRADE is enabled."""
    if not config.AUTO_TRADE_ENABLED:
        return False
        
    try:
        exchange = _get_exchange()
        
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
        return True
    except Exception as e:
        logger.error("❌ Failed to execute entry order: %s", e)
        return False

def execute_exit(trade) -> bool:
    """Closes an active position if AUTO_TRADE is enabled."""
    if not config.AUTO_TRADE_ENABLED:
        return False
        
    try:
        exchange = _get_exchange()
        price = trade.entry_price
        
        raw_amount = config.POSITION_SIZE_USD / price
        
        try:
            exchange.load_markets()
            amount = float(exchange.amount_to_precision(trade.symbol, raw_amount))
        except Exception:
            amount = raw_amount
        
        # Inverse the direction to close the trade
        side = 'sell' if trade.direction == 'BUY' else 'buy'
        
        logger.info("🛑 EXECUTING TESTNET CLOSE: %s %.6f %s", side.upper(), amount, trade.symbol)
        
        order = exchange.create_market_order(trade.symbol, side, amount, params={'reduceOnly': True})
        logger.info("✅ Close Order Filled! ID: %s", order.get('id', 'N/A'))
        return True
    except Exception as e:
        logger.error("❌ Failed to execute close order: %s", e)
        return False
