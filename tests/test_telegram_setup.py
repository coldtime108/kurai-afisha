import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import BotCommand
from kurai import telegram_setup


def fake_bot(monkeypatch, username="kurai_test_bot", webhook=""):
    bot = AsyncMock()
    bot.context = MagicMock(return_value=bot)
    bot.__aenter__.return_value = bot
    bot.get_me.return_value = SimpleNamespace(username=username)
    bot.get_webhook_info.return_value = SimpleNamespace(url=webhook)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:OFFLINE_TEST_ONLY")
    monkeypatch.setattr(telegram_setup, "Bot", MagicMock(return_value=bot))
    return bot


def test_setup_accepts_commands_read_back_with_transport_binding(monkeypatch):
    bot = fake_bot(monkeypatch)

    async def read_commands(**kwargs):
        # Telegram's response binds models to a bot; the submitted models are unbound.
        return [
            BotCommand.model_validate(command.model_dump()).as_(bot)
            for command in bot.set_my_commands.call_args.args[0]
        ]

    bot.get_my_commands.side_effect = read_commands
    result = asyncio.run(telegram_setup.configure("kurai_test_bot"))
    assert result["username"] == "kurai_test_bot" and result["polling_available"]
    registered = {command.command for command in bot.set_my_commands.call_args.args[0]}
    assert {"start", "catalog", "subscribe", "unsubscribe", "help"} <= registered
    # Verification must not acknowledge and discard a queued user's /start.
    assert "offset" not in bot.get_updates.call_args.kwargs


@pytest.mark.parametrize("wrong_identity", [True, False])
def test_setup_preserves_other_bots_and_existing_webhooks(monkeypatch, wrong_identity):
    bot = fake_bot(
        monkeypatch,
        username="another_bot" if wrong_identity else "kurai_test_bot",
        webhook="" if wrong_identity else "https://example.org/existing-webhook",
    )
    with pytest.raises(SystemExit):
        asyncio.run(telegram_setup.configure("kurai_test_bot"))
    bot.set_my_commands.assert_not_awaited()
    bot.set_my_description.assert_not_awaited()
    bot.get_updates.assert_not_awaited()
