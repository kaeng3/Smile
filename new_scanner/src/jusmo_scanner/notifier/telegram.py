from __future__ import annotations
import logging

import requests

logger = logging.getLogger(__name__)


class TelegramSendError(RuntimeError):
    """Raised when a Telegram API call fails. Deliberately carries no
    exception chaining (`from None`) and no original exception message —
    both could embed the bot token, since it's part of the request URL —
    only the failing exception's type name."""


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self._bot_token = bot_token
        self._chat_id = chat_id

    def send_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            response = requests.post(url, data={"chat_id": self._chat_id, "text": text}, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Telegram request failed: %s", type(exc).__name__)
            raise TelegramSendError(f"Telegram request failed: {type(exc).__name__}") from None
