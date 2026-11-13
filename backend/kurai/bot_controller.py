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


@dataclass
class BotReply:
    text: str
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)


def event_text(event):
    local = event.date_start.astimezone(LOCAL_TZ)
    price = (
        "Бесплатно"
        if event.is_free
        else (
            "Цена уточняется у организатора"
            if event.price_min is None
            else f"от {event.price_min} ₽ за билет"
        )
    )
    age = "Возраст не указан" if event.age_limit is None else f"{event.age_limit}+"
    return f"{event.title}\n{local:%d.%m.%Y, %H:%M} · время Башкортостана\n{event.city} · {event.venue}\n{event.address}\n{price} · {age}"


class BotController:
    def __init__(self, sessions, clock=utcnow):
        self.sessions, self.clock = sessions, clock

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

            window = data.get("rate", {})
            if (
                window
                and now.timestamp() - window.get("start", 0) < 60
                and window.get("count", 0) >= 30
                and text != "/unsubscribe"
            ):
                return finish(
                    BotReply(
                        "Слишком много запросов. Попробуйте через минуту. /unsubscribe доступна всегда."
                    )
                )
            data["rate"] = (
                {"start": window["start"], "count": window["count"] + 1}
                if window and now.timestamp() - window.get("start", 0) < 60
                else {"start": now.timestamp(), "count": 1}
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
                parts = [context, f"Найдено: {total}. Цена — за один билет."]
                buttons = []
                for i, item in enumerate(items, 1):
                    parts.append(event_text(item))
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
                return BotReply("\n\n".join(parts), buttons)

            def cities(subscribe=False):
                values = sorted(
                    set(CITIES)
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
                    f"Подписка: {proposal['city']} · {CATEGORIES.get(proposal['category'],'все категории')}.\nНовые события на неделю, не чаще одного сообщения в день в 18:00 по времени Башкортостана.\nСрок — 180 дней. /unsubscribe удалит подписку. Подтвердить?",
                    [[("Подтвердить", f"confirm:{nonce}"), ("Не сохранять", "cancel")]],
                )

            if text in ("/start", "/help"):
                data.pop("awaiting", None)
                return finish(
                    BotReply(
                        "Курай — культура Башкортостана рядом.\nВыбирайте кнопками или напишите: «концерт в Уфе в субботу до 1000 рублей».\nДанные берём из афиш учреждений. Это независимый проект.\n/help — помощь, /cancel — отмена, /unsubscribe — отписка, /feedback — обращение.",
                        [
                            [("Открыть афишу", "catalog")],
                            [("Моя подписка", "subscription")],
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
                return finish(
                    BotReply(
                        "Действие отменено. Подписка не изменена.",
                        [[("К афише", "catalog")]],
                    )
                )
            if text == "/subscribe" or callback == "subscribe":
                return finish(subscription_preview())
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
                            [[("Изменить", "cities"), ("К афише", "catalog")]],
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
            if callback and callback.startswith("e:"):
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
                description = item.description[:1400]
                details = f"Категория: {CATEGORIES.get(item.category,'Событие')}\nПродолжительность: {str(item.duration_min)+' мин' if item.duration_min else 'не указана'}\nЯзык: {item.language or 'не указан'}"
                sources = [
                    [(f"Источник {i+1}", "url:" + s["url"])]
                    for i, s in enumerate(item.sources[:5])
                ]
                if item.org_link:
                    sources.append([("Билеты / организатор", "url:" + item.org_link)])
                return finish(
                    BotReply(
                        cancelled
                        + event_text(item)
                        + "\n\n"
                        + details
                        + "\n\n"
                        + description
                        + "\n\nПеред посещением сверьтесь с организатором.",
                        sources + [[("К афише", "catalog")]],
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
            if text:
                if text.startswith("/"):
                    return finish(
                        BotReply(
                            "Команда не найдена. /help — список команд.",
                            [[("К афише", "catalog")]],
                        )
                    )
                known_cities = set(CITIES) | set(session.scalars(
                    select(Event.city).where(Event.status == "published").distinct()
                ))
                try:
                    filters = parse_query(text[:500], filters, now, cities=known_cities)
                except QueryParseError as error:
                    return finish(BotReply(str(error), [[("К афише", "catalog")]]))
            return finish(catalog())
