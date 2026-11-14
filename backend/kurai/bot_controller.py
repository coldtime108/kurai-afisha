"""Telegram interaction logic, independently testable without network access."""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID
from sqlalchemy import select
from .catalog import Filters, LOCAL_TZ, search
from .models import BotDialog, Event, Feedback, Subscription, utcnow
from .query_parser import CITIES, QueryParseError, parse_query
from .schemas import CATEGORIES, SubscriptionFilter
from .subscriptions import (
    delete_subscription,
    owner_hash,
    period_bounds,
    save_subscription,
)
from .assistant import AssistantBusy
from .bot_planner import handle_planner, plan_reply


@dataclass
class BotReply:
    text: str
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)


def event_text(event, compact=False):
    local = event.date_start.astimezone(LOCAL_TZ)
    if event.is_free:
        price = "Бесплатно"
    elif event.price_min is None:
        price = "Цена уточняется"
    elif event.price_max == event.price_min:
        price = f"{event.price_min} ₽ за билет"
    elif event.price_max is not None:
        price = f"{event.price_min}–{event.price_max} ₽ за билет"
    else:
        price = f"от {event.price_min} ₽ за билет"
    age = "Возраст не указан" if event.age_limit is None else f"{event.age_limit}+"
    if compact:
        return f"{event.title}\n{local:%d.%m, %H:%M} · {event.venue}\n{event.city} · {price} · {age}"
    return f"{event.title}\n{local:%d.%m.%Y, %H:%M} · время РБ (UTC+5)\n{event.city} · {event.venue}\n{event.address}\n{price} · {age}"


class BotController:
    def __init__(self, sessions, clock=utcnow, assistant=None):
        self.sessions, self.clock = sessions, clock
        self.assistant = assistant

    def handle(
        self, user_id: int, text: str | None = None, callback: str | None = None
    ):
        owner = owner_hash("telegram", user_id)
        now = self.clock()
        with self.sessions() as session:
            state = session.get(BotDialog, owner)
            if not state:
                state = BotDialog(
                    owner_hash=owner, data={}, expires_at=now + timedelta(days=1)
                )
                session.add(state)
            data = dict(state.data) if state.expires_at > now else {}
            filters = dict(data.get("filters", {}))

            def finish(reply):
                data["filters"] = filters
                state.data = data
                state.expires_at = now + timedelta(days=1)
                session.commit()
                return reply

            def assistant_reply(reply):
                nonlocal filters
                filters = dict(reply.filters)
                if reply.plan:
                    data["day_plan_request"] = reply.plan.input.model_dump(mode="json")
                    return BotReply(*plan_reply(reply.plan))
                parts = [reply.message]
                buttons = []
                for index, card in enumerate(reply.cards, 1):
                    parts.append(
                        f"{index}. "
                        + event_text(card.event, compact=True)
                        + ("\n" + " · ".join(card.reasons[:2]) if card.reasons else "")
                    )
                    buttons.append(
                        [
                            (f"{index}. {card.event.title[:42]}", "e:" + card.event.id),
                            ("Источник", "url:" + str(card.event.source_url)),
                        ]
                    )
                parts.extend(reply.suggestions)
                if reply.pending:
                    parts.append(reply.pending.summary)
                    buttons.append(
                        [
                            ("Подтвердить", "ai-yes:" + reply.pending.token),
                            ("Отмена", "ai-no:" + reply.pending.token),
                        ]
                    )
                if reply.has_more:
                    buttons.append([("Показать ещё", "ai-more")])
                buttons.append([("К афише", "catalog"), ("Новый диалог", "ai-reset")])
                return BotReply("\n\n".join(parts), buttons)

            window = data.get("rate", {})
            assistant_interaction = self.assistant and (
                (
                    text
                    and not text.startswith("/")
                    and data.get("awaiting") != "feedback"
                )
                or text == "/new"
                or callback in ("assistant", "ai-example", "ai-more", "ai-reset")
                or (callback and callback.startswith(("ai-yes:", "ai-no:")))
            )
            if (
                window
                and not assistant_interaction
                and now.timestamp() - window.get("start", 0) < 60
                and window.get("count", 0) >= 30
                and text != "/unsubscribe"
            ):
                return finish(
                    BotReply(
                        "Слишком много запросов. Попробуйте через минуту. /unsubscribe доступна всегда."
                    )
                )
            if not assistant_interaction:
                data["rate"] = (
                    {"start": window["start"], "count": window["count"] + 1}
                    if window and now.timestamp() - window.get("start", 0) < 60
                    else {"start": now.timestamp(), "count": 1}
                )
            if text in (
                "/start",
                "/help",
                "/cancel",
                "/new",
                "/catalog",
                "/subscribe",
                "/unsubscribe",
                "/feedback",
            ) or callback in ("catalog", "cancel", "assistant", "help", "home"):
                data.pop("planner_wizard", None)
                if text == "/new":
                    data.pop("day_plan_request", None)
            if (
                text == "/plan"
                or callback == "planner"
                or (callback and callback.startswith("dp:"))
                or (data.get("planner_wizard") and text and not text.startswith("/"))
            ):
                try:
                    planned = handle_planner(session, data, text, callback, now)
                    if planned:
                        if data.get("day_plan_request"):
                            values = data["day_plan_request"]
                            filters = {
                                "city": values["city"],
                                "date_from": values["day"],
                                "date_to": values["day"],
                            }
                        return finish(BotReply(*planned))
                except ValueError:
                    data.pop("planner_wizard", None)
                    return finish(
                        BotReply(
                            "Условия устарели или не удалось разобрать ввод. Начните план заново: /plan.",
                            [[("Спланировать день", "planner")]],
                        )
                    )

            def catalog(page=1):
                data["page"] = page
                allowed = {
                    k: v
                    for k, v in filters.items()
                    if k in Filters.__dataclass_fields__
                }
                for key in ("date_from", "date_to"):
                    if allowed.get(key):
                        allowed[key] = date.fromisoformat(allowed[key])
                if not allowed.get("date_from"):
                    allowed["date_from"] = now.astimezone(LOCAL_TZ).date()
                items, total, suggestions = search(
                    session, Filters(**allowed), page=page, size=3
                )
                context = f"Город: {filters.get('city','вся республика')} · {CATEGORIES.get(filters.get('category'),'все категории')}"
                parts = [context, f"Найдено: {total} · время РБ (UTC+5)."]
                buttons = []
                for i, item in enumerate(items, 1):
                    parts.append(f"{i}. " + event_text(item, compact=True))
                    buttons.append([(f"{i}. {item.title[:45]}", "e:" + item.id)])
                if not items:
                    parts.append("Нет подходящих данных. " + ". ".join(suggestions))
                if page * 3 < total:
                    buttons.append([("Показать ещё", f"page:{page+1}")])
                buttons.extend(
                    [
                        [
                            ("Сегодня", "period:today"),
                            ("Завтра", "period:tomorrow"),
                            ("Выходные", "period:weekend"),
                        ],
                        [("Город", "cities"), ("Категория", "categories")],
                        [("Подписаться", "subscribe"), ("Сбросить фильтры", "reset")],
                    ]
                )
                if self.assistant:
                    buttons.append([("Подобрать с помощником", "assistant")])
                return BotReply("\n\n".join(parts), buttons)

            def cities(subscribe=False):
                values = sorted(
                    (set(CITIES) if subscribe else set())
                    | set(
                        session.scalars(
                            select(Event.city).where(Event.status == "published")
                        ).all()
                    )
                )
                data["cities"] = values
                data["choosing_subscription"] = subscribe
                return BotReply(
                    "Выберите город",
                    [[(city, f"city:{i}")] for i, city in enumerate(values)]
                    + [[("К афише", "catalog")]],
                )

            def subscription_preview():
                if not filters.get("city"):
                    return cities(subscribe=True)
                nonce = secrets.token_hex(8)
                proposal = SubscriptionFilter(
                    city=filters["city"],
                    category=filters.get("category"),
                    period="week",
                ).model_dump(mode="json")
                data["pending"] = {
                    "nonce": nonce,
                    "filters": proposal,
                    "expires": (now + timedelta(minutes=10)).isoformat(),
                }
                return BotReply(
                    f"Подписка: {proposal['city']} · {CATEGORIES.get(proposal['category'],'все категории')}\n\nНовинки на неделю · до 1 сообщения в день, в 18:00 по времени РБ.\nСрок — 180 дней. Удаление: /unsubscribe.\n\nПодтвердить?",
                    [[("Подтвердить", f"confirm:{nonce}"), ("Не сохранять", "cancel")]],
                )

            if text == "/help" or callback == "help":
                data.pop("awaiting", None)
                return finish(
                    BotReply(
                        "Курай · помощь\n\n/catalog — афиша и фильтры\n/plan — культурный день\n/subscribe — подписка\n/unsubscribe — удалить подписку\n/feedback — сообщить об изменении\n/cancel — отменить действие\n/new — удалить диалог помощника\n\nВремя событий — Башкортостан, UTC+5.\nСвободные запросы передаются NVIDIA. Память — 24 часа, диагностика — 7 дней. Не указывайте личные данные и ключи. /new удаляет диалог и его диагностику.\n\nНезависимый проект. Сведения и билеты можно проверить по ссылке в карточке.",
                        [[("Открыть афишу", "catalog"), ("В начало", "home")]],
                    )
                )
            if text == "/start" or callback == "home":
                data.pop("awaiting", None)
                return finish(
                    BotReply(
                        "Курай · Афиша Башкортостана\n\nНайдите событие или соберите культурный день. Выберите действие ниже — или напишите город, дату и пожелания.\n\nСвободный запрос передаётся NVIDIA. Не указывайте личные данные и ключи. /help — команды и сведения о данных.",
                        [
                            [
                                ("Открыть афишу", "catalog"),
                                ("Подобрать с помощником", "assistant"),
                            ],
                            [
                                ("Спланировать день", "planner"),
                                ("Моя подписка", "subscription"),
                            ],
                            [("О проекте и помощь", "help")],
                        ],
                    )
                )
            if callback == "assistant" and self.assistant:
                data.pop("awaiting", None)
                data.pop("pending", None)
                data.pop("feedback_pending", None)
                return finish(
                    BotReply(
                        "Помощник Курай\n\nНапишите город, дату, бюджет и возраст ребёнка, если идёте с ним. Например: «Спектакль в Стерлитамаке на выходных до 800 рублей».\n\nЗатем уточняйте: «подешевле» или «подробнее о первом». Факты — из каталога, разбор запроса — NVIDIA.\n/new — начать заново; /help — о данных.",
                        [
                            [("Попробовать пример", "ai-example")],
                            [("К афише", "catalog")],
                        ],
                    )
                )
            if text == "/catalog":
                data.pop("awaiting", None)
                return finish(catalog())
            if text == "/unsubscribe":
                delete_subscription(session, owner, "telegram")
                # delete_subscription removes the private dialog too.
                return BotReply(
                    "Подписка и её данные удалены. Уведомлений больше не будет.",
                    [[("Открыть афишу", "catalog")]],
                )
            if text == "/cancel" or callback == "cancel":
                data.pop("pending", None)
                data.pop("awaiting", None)
                data.pop("feedback_pending", None)
                if self.assistant:
                    self.assistant.reset(owner)
                return finish(
                    BotReply(
                        "Действие отменено. Подписка не изменена.",
                        [[("К афише", "catalog")]],
                    )
                )
            if text == "/subscribe" or callback == "subscribe":
                return finish(subscription_preview())
            if callback == "subscription-edit":
                sub = session.scalar(
                    select(Subscription).where(
                        Subscription.owner_hash == owner,
                        Subscription.channel == "telegram",
                    )
                )
                if sub and sub.expires_at > now:
                    filters = dict(sub.filters)
                return finish(cities(subscribe=True))
            if text == "/feedback":
                data["awaiting"] = "feedback"
                return finish(
                    BotReply(
                        "Напишите, что нужно добавить или исправить, и ссылку на источник (10–2000 символов). Не указывайте личные данные. Затем подтвердите отправку. /cancel — отмена."
                    )
                )
            if callback and callback.startswith("feedback-confirm:"):
                proposal = data.pop("feedback_pending", None)
                if (
                    not proposal
                    or not secrets.compare_digest(callback[17:], proposal["nonce"])
                    or datetime.fromisoformat(proposal["expires"]) <= now
                ):
                    return finish(
                        BotReply("Подтверждение устарело. Начните с /feedback.")
                    )
                session.add(Feedback(message=proposal["message"]))
                return finish(BotReply("Обращение сохранено в очереди модерации."))
            if text and data.get("awaiting") == "feedback" and not text.startswith("/"):
                if not 10 <= len(text) <= 2000:
                    return finish(
                        BotReply(
                            "Нужно сообщение длиной 10–2000 символов. /cancel — отмена."
                        )
                    )
                nonce = secrets.token_hex(8)
                data["feedback_pending"] = {
                    "message": text,
                    "nonce": nonce,
                    "expires": (now + timedelta(minutes=10)).isoformat(),
                }
                data.pop("awaiting", None)
                return finish(
                    BotReply(
                        "Отправить модератору?\n\n" + text,
                        [
                            [
                                ("Подтвердить отправку", "feedback-confirm:" + nonce),
                                ("Отмена", "cancel"),
                            ]
                        ],
                    )
                )
            if callback == "subscription":
                sub = session.scalar(
                    select(Subscription).where(
                        Subscription.owner_hash == owner,
                        Subscription.channel == "telegram",
                    )
                )
                if sub and sub.expires_at > now:
                    return finish(
                        BotReply(
                            f"Ваша подписка: {sub.filters['city']} · {CATEGORIES.get(sub.filters.get('category'),'все категории')}.\nОтписка одной командой: /unsubscribe",
                            [
                                [
                                    ("Изменить город", "subscription-edit"),
                                    ("К афише", "catalog"),
                                ]
                            ],
                        )
                    )
                return finish(subscription_preview())
            if callback and callback.startswith("confirm:"):
                proposal = data.pop("pending", None)
                if (
                    not proposal
                    or not secrets.compare_digest(callback[8:], proposal["nonce"])
                    or datetime.fromisoformat(proposal["expires"]) <= now
                ):
                    return finish(
                        BotReply(
                            "Подтверждение устарело. Откройте подписку заново.",
                            [[("Подписаться", "subscribe")]],
                        )
                    )
                save_subscription(
                    session,
                    owner,
                    "telegram",
                    SubscriptionFilter.model_validate(proposal["filters"]),
                    confirmed=True,
                    telegram_id=user_id,
                    now=now,
                )
                return finish(
                    BotReply(
                        "Подписка сохранена. /unsubscribe — удалить подписку.",
                        [[("К афише", "catalog")]],
                    )
                )
            if callback and callback.startswith(("e:", "d:")):
                try:
                    item = session.get(Event, str(UUID(callback[2:])))
                except ValueError:
                    item = None
                if not item or item.status == "draft":
                    return finish(
                        BotReply(
                            "Событие не найдено или ещё проходит проверку.",
                            [[("К афише", "catalog")]],
                        )
                    )
                cancelled = (
                    "МЕРОПРИЯТИЕ ОТМЕНЕНО\n\n" if item.status == "cancelled" else ""
                )
                expanded = callback.startswith("d:")
                description = item.description
                limit = 1400 if expanded else 260
                preview = (
                    description
                    if len(description) <= limit
                    else description[:limit].rsplit(" ", 1)[0] + "…"
                )
                details = [
                    CATEGORIES.get(item.category, "Событие"),
                    (
                        f"{item.duration_min} мин"
                        if item.duration_min
                        else "длительность уточняется"
                    ),
                ]
                if item.language:
                    details.append(item.language)
                buttons, seen = [], set()
                for entry in item.sources[:5]:
                    if entry["url"] not in seen:
                        seen.add(entry["url"])
                        buttons.append(
                            [
                                (
                                    (
                                        "Источник"
                                        if len(item.sources) == 1
                                        else f"Источник {len(buttons)+1}"
                                    ),
                                    "url:" + entry["url"],
                                )
                            ]
                        )
                if item.org_link and str(item.org_link) not in seen:
                    buttons.append(
                        [("Билеты / организатор", "url:" + str(item.org_link))]
                    )
                if len(description) > 260 and not expanded:
                    buttons.insert(0, [("Читать описание", "d:" + item.id)])
                if expanded:
                    buttons.append([("К карточке", "e:" + item.id)])
                buttons.append([("К афише", "catalog")])
                return finish(
                    BotReply(
                        cancelled
                        + event_text(item)
                        + "\n\n"
                        + " · ".join(details)
                        + "\n\n"
                        + preview
                        + "\n\nИзменения программы и билеты — у организатора.",
                        buttons,
                    )
                )
            if callback == "cities":
                return finish(cities())
            if callback == "categories":
                return finish(
                    BotReply(
                        "Выберите категорию",
                        [
                            [(label, "category:" + key)]
                            for key, label in CATEGORIES.items()
                        ]
                        + [[("Все категории", "category:all")]],
                    )
                )
            if callback and callback.startswith("city:"):
                try:
                    city = data.get("cities", [])[int(callback[5:])]
                except (ValueError, IndexError):
                    return finish(cities())
                filters["city"] = city
                return finish(
                    subscription_preview()
                    if data.pop("choosing_subscription", False)
                    else catalog()
                )
            if callback and callback.startswith("category:"):
                category = callback[9:]
                if category in CATEGORIES:
                    filters["category"] = category
                elif category == "all":
                    filters.pop("category", None)
                return finish(catalog())
            if callback and callback.startswith("period:"):
                period = callback[7:]
                if period not in ("today", "tomorrow", "weekend", "week"):
                    return finish(catalog())
                start, end = period_bounds(period, now)
                filters.update(date_from=start.isoformat(), date_to=end.isoformat())
                return finish(catalog())
            if callback == "reset":
                filters = {}
                return finish(catalog())
            if callback and callback.startswith("page:"):
                try:
                    page = max(1, min(int(callback[5:]), 10000))
                except ValueError:
                    page = 1
                return finish(catalog(page))
            if self.assistant and (text == "/new" or callback == "ai-reset"):
                self.assistant.reset(owner)
                filters = {}
                return finish(
                    BotReply(
                        "Диалог и его диагностические записи удалены. Напишите новый запрос.",
                        [[("К афише", "catalog")]],
                    )
                )
            if (
                self.assistant
                and callback
                and callback.startswith(("ai-yes:", "ai-no:"))
            ):
                try:
                    token = callback.split(":", 1)[1]
                    return finish(
                        assistant_reply(
                            self.assistant.confirm(
                                owner,
                                "telegram",
                                token,
                                callback.startswith("ai-yes:"),
                                telegram_id=user_id,
                            )
                        )
                    )
                except AssistantBusy:
                    return finish(
                        BotReply(
                            "Предыдущий запрос ещё обрабатывается. Подождите немного."
                        )
                    )
            if self.assistant and (
                text
                and not text.startswith("/")
                or callback in ("ai-more", "ai-example")
            ):
                try:
                    reply = self.assistant.respond(
                        owner,
                        "telegram",
                        text
                        or (
                            "Спектакль в Стерлитамаке на выходных до 800 рублей"
                            if callback == "ai-example"
                            else "Покажи ещё"
                        ),
                        telegram_id=user_id,
                        initial_filters=filters,
                    )
                    return finish(assistant_reply(reply))
                except AssistantBusy:
                    return finish(
                        BotReply(
                            "Предыдущий запрос ещё обрабатывается. Подождите немного."
                        )
                    )
            if text:
                if text.startswith("/"):
                    return finish(
                        BotReply(
                            "Команда не найдена. /help — список команд.",
                            [[("К афише", "catalog")]],
                        )
                    )
                known_cities = set(CITIES) | set(
                    session.scalars(
                        select(Event.city).where(Event.status == "published").distinct()
                    )
                )
                try:
                    filters = parse_query(text[:500], filters, now, cities=known_cities)
                except QueryParseError as error:
                    return finish(BotReply(str(error), [[("К афише", "catalog")]]))
            return finish(catalog())
