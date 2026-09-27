from __future__ import annotations
import logging
from unittest.mock import patch, MagicMock

import pytest

from jusmo_scanner.notifier.telegram import TelegramNotifier, TelegramSendError


def test_send_message_posts_to_telegram_api():
    notifier = TelegramNotifier(bot_token="SECRETTOKEN", chat_id="123")
    with patch("jusmo_scanner.notifier.telegram.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        notifier.send_message("hello")
    args, kwargs = mock_post.call_args
    assert "SECRETTOKEN" in args[0]  # URL does contain the token (required by Telegram API)
    assert kwargs["data"]["chat_id"] == "123"
    assert kwargs["data"]["text"] == "hello"


def test_send_message_failure_raises_telegram_send_error():
    notifier = TelegramNotifier(bot_token="SECRETTOKEN", chat_id="123")
    response = MagicMock(status_code=403)
    response.raise_for_status.side_effect = Exception("https://api.telegram.org/botSECRETTOKEN/sendMessage failed")
    with patch("jusmo_scanner.notifier.telegram.requests.post", return_value=response):
        with pytest.raises(TelegramSendError):
            notifier.send_message("hello")


def test_telegram_token_never_appears_in_exception():
    notifier = TelegramNotifier(bot_token="SECRETTOKEN", chat_id="123")
    response = MagicMock(status_code=403)
    response.raise_for_status.side_effect = Exception("https://api.telegram.org/botSECRETTOKEN/sendMessage failed")
    with patch("jusmo_scanner.notifier.telegram.requests.post", return_value=response):
        try:
            notifier.send_message("hello")
            assert False, "expected TelegramSendError"
        except TelegramSendError as exc:
            assert "SECRETTOKEN" not in str(exc)
            assert exc.__cause__ is None  # `from None` suppresses exception chaining


def test_telegram_token_never_appears_in_logs(caplog):
    notifier = TelegramNotifier(bot_token="SECRETTOKEN", chat_id="123")
    response = MagicMock(status_code=403)
    response.raise_for_status.side_effect = Exception("https://api.telegram.org/botSECRETTOKEN/sendMessage failed")
    with patch("jusmo_scanner.notifier.telegram.requests.post", return_value=response):
        with caplog.at_level(logging.WARNING):
            try:
                notifier.send_message("hello")
            except TelegramSendError:
                pass
    for record in caplog.records:
        assert "SECRETTOKEN" not in record.getMessage()
