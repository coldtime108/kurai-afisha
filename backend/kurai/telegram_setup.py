"""One-time, explicit registration of the Telegram bot's public profile."""

import argparse
import asyncio
import json
import logging
import os

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands


async def configure(expected_username: str | None = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Задайте TELEGRAM_BOT_TOKEN в локальных настройках запуска.")
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    async with Bot(token, session=AiohttpSession(timeout=15)).context() as bot:
        identity = await bot.get_me()
        if expected_username and identity.username != expected_username.lstrip("@"):
            raise SystemExit("Токен принадлежит другому боту. Настройки не изменены.")
        if (await bot.get_webhook_info()).url:
            raise SystemExit("Сначала выберите режим запуска: у бота уже есть webhook.")
        commands = [
            BotCommand(command="start", description="Начать и открыть главное меню"),
            BotCommand(command="catalog", description="Афиша и фильтры событий"),
            BotCommand(command="subscribe", description="Подписаться на город и категорию"),
            BotCommand(command="unsubscribe", description="Удалить подписку и её данные"),
            BotCommand(command="feedback", description="Сообщить о событии или исправлении"),
            BotCommand(command="cancel", description="Отменить незавершённое действие"),
            BotCommand(command="help", description="Помощь и команды"),
        ]
        scope = BotCommandScopeAllPrivateChats()
        await bot.set_my_commands(commands, scope=scope)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        await bot.set_my_name(name="Курай · Афиша Башкортостана")
        await bot.set_my_short_description(
            short_description="Культурные события Башкортостана: афиша, поиск и подписки. Независимый проект."
        )
        await bot.set_my_description(
            description=(
                "Курай — культура Башкортостана рядом.\n\n"
                "Концерты, спектакли и другие события из афиш учреждений. "
                "Выберите город, дату и категорию или напишите свой запрос. "
                "В карточках — источники и ссылки организаторов.\n\n"
                "Подписка на новые события — с вашим подтверждением. "
                "Независимый проект, не официальный сервис министерства.\n\n"
                "Нажмите «Начать», чтобы открыть афишу."
            )
        )
        registered = await bot.get_my_commands(scope=scope)
        if [(item.command, item.description) for item in registered] != [
            (item.command, item.description) for item in commands
        ]:
            raise SystemExit("Telegram не подтвердил сохранение команд.")
        # A short poll verifies connectivity without acknowledging or printing updates.
        await bot.get_updates(timeout=1, limit=1, allowed_updates=["message", "callback_query"])
        return {"username": identity.username, "commands": len(registered), "polling_available": True}


def main():
    parser = argparse.ArgumentParser(description="Настроить публичный профиль Telegram-бота")
    parser.add_argument("--expected-username")
    args = parser.parse_args()
    try:
        result = asyncio.run(configure(args.expected_username))
    except Exception as error:
        # Never print transport exception messages: Telegram URLs contain credentials.
        print(json.dumps({"configured": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
