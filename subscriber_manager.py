import json
import os
import logging

logger = logging.getLogger(__name__)

_FILE = "subscribers.json"
_subscribers: set[int] = set()

def load_subscribers():
    global _subscribers
    if os.path.exists(_FILE):
        try:
            with open(_FILE, "r") as f:
                _subscribers = set(json.load(f))
            logger.info("Loaded %d subscribers.", len(_subscribers))
        except Exception as e:
            logger.error("Failed to load subscribers: %s", e)
            _subscribers = set()
    return _subscribers

def save_subscribers():
    try:
        with open(_FILE, "w") as f:
            json.dump(list(_subscribers), f)
    except Exception as e:
        logger.error("Failed to save subscribers: %s", e)

def add_subscriber(chat_id: int) -> bool:
    """Add a chat ID to the list of subscribers. Returns True if newly added."""
    if chat_id not in _subscribers:
        _subscribers.add(chat_id)
        save_subscribers()
        logger.info("Added new subscriber: %s", chat_id)
        return True
    return False

def remove_subscriber(chat_id: int) -> bool:
    """Remove a chat ID from the list. Returns True if removed."""
    if chat_id in _subscribers:
        _subscribers.remove(chat_id)
        save_subscribers()
        logger.info("Removed subscriber: %s", chat_id)
        return True
    return False

def get_subscribers() -> list[int]:
    """Return the list of subscriber chat IDs."""
    return list(_subscribers)
