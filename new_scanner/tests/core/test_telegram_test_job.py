from __future__ import annotations
from unittest.mock import patch
from jusmo_scanner.jobs import telegram_test


def test_main_sends_test_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr("jusmo_scanner.jobs.telegram_test.load_dotenv", lambda *a, **k: None)
    with patch("jusmo_scanner.notifier.telegram.TelegramNotifier.send_message") as mock_send:
        telegram_test.main()
    mock_send.assert_called_once()
    assert "테스트" in mock_send.call_args[0][0] or "test" in mock_send.call_args[0][0].lower()
