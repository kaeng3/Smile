from __future__ import annotations
import logging

from dotenv import load_dotenv

from jusmo_scanner.config import load_telegram_credentials
from jusmo_scanner.notifier.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    token, chat_id = load_telegram_credentials()
    notifier = TelegramNotifier(bot_token=token, chat_id=chat_id)
    notifier.send_message("jusmo-scanner 테스트 메시지입니다.")
    logger.info("test message sent")


if __name__ == "__main__":
    main()
