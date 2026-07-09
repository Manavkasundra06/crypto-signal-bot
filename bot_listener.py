import time
import requests
import logging
import threading

import config
import subscriber_manager

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
        "Type /stop at any time to unsubscribe."
    )
    _send_message(chat_id, msg)

def _send_goodbye(chat_id: int):
    msg = (
        "🔴 *Unsubscribed!*\n\n"
        "You will no longer receive any alerts.\n"
        "Type /start to resubscribe."
    )
    _send_message(chat_id, msg)

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
