"""Small deterministic search parser; no model and no invented event facts."""

import re
from datetime import date, timedelta
from difflib import get_close_matches
from .ingestion import normalize
from .catalog import LOCAL_TZ
from .subscriptions import period_bounds

CITIES = [
    "Уфа",
    "Стерлитамак",
    "Салават",
    "Нефтекамск",
    "Октябрьский",
    "Белорецк",
    "Туймазы",
    "Ишимбай",
    "Кумертау",
    "Мелеуз",
    "Сибай",
    "Белебей",
    "Бирск",
    "Янаул",
]
ALIASES = {
    "уфе": "Уфа",
    "уфу": "Уфа",
    "стерлитамаке": "Стерлитамак",
    "салавате": "Салават",
    "нефтекамске": "Нефтекамск",
    "октябрьском": "Октябрьский",
    "белорецке": "Белорецк",
    "туймазах": "Туймазы",
    "ишимбае": "Ишимбай",
    "кумертау": "Кумертау",
    "мелеузе": "Мелеуз",
    "сибае": "Сибай",
    "белебее": "Белебей",
    "бирске": "Бирск",
    "янауле": "Янаул",
}
WORDS = {
    "concert": ["концерт", "концерты", "концертов", "музыка"],
    "theatre": [
        "театр",
        "спектакль",
        "спектакли",
        "спектаклей",
        "балет",
        "балеты",
        "опера",
        "оперы",
    ],
    "exhibition": ["выставка", "выставки", "выставок"],
    "festival": ["фестиваль", "фестивали", "фестивалей"],
    "cinema": ["кино", "кинопоказ"],
    "excursion": ["экскурсия", "экскурсии"],
}

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


class QueryParseError(ValueError):
    """An explicit invalid constraint must not silently turn into a broad search."""


def parse_query(text: str, previous: dict, now, cities=None):
    result = dict(previous)
    working = normalize(text)
    aliases = {normalize(v): v for v in (cities or CITIES)} | ALIASES
    for word in working.split():
        match = get_close_matches(word, aliases, n=1, cutoff=0.79)
        if match:
            result["city"] = aliases[match[0]]
            working = working.replace(word, " ")
            break
    for category, words in WORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", working) for word in words):
            result["category"] = category
            for word in words:
                working = re.sub(rf"\b{re.escape(word)}\b", " ", working)
            break
    budget = re.search(
        r"\bдо\s+(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d{1,8})"
        r"(?![\d:./-])(?:\s*(?:руб(?:лей|ля|ль)?\.?|₽))?",
        text.lower(),
    )
    if budget:
        if re.match(
            r"\s*(?:" + "|".join(MONTHS) + r")\b", text[budget.end(1) :].lower()
        ):
            budget = None
        else:
            amount = int(re.sub(r"\s", "", budget[1]))
            if amount > 10_000_000:
                raise QueryParseError(
                    "Укажите бюджет до 10 000 000 рублей за один билет."
                )
            result["price_max"] = amount
            working = working.replace(normalize(budget[0]), " ")
    if "бесплат" in working:
        result["is_free"] = True
        working = re.sub(r"бесплат\w*", " ", working)
    child = re.search(
        r"(?:реб[её]н\w*|дет\w*|подрост\w*|возраст\w*)\s+(\d{1,3})\s*(?:лет|год)",
        text.lower(),
    )
    if child and int(child[1]) <= 120:
        result["age"] = int(child[1])
        working = re.sub(
            r"(?:ребен\w*|дет\w*|подрост\w*|возраст\w*)\s+\d+\s+(?:лет|год\w*)",
            " ",
            working,
        )
    period = next(
        (
            p
            for p, trigger in [
                ("today", "сегодня"),
                ("tomorrow", "завтра"),
                ("weekend", "выходн"),
                ("week", "недел"),
            ]
            if trigger in working
        ),
        None,
    )
    if period:
        start, end = period_bounds(period, now)
        result.update(date_from=start.isoformat(), date_to=end.isoformat())
        working = re.sub(r"сегодня|завтра|выходн\w*|недел\w*", " ", working)
    weekdays = [
        "понедельник",
        "вторник",
        "среду",
        "четверг",
        "пятницу",
        "субботу",
        "воскресенье",
    ]
    for i, word in enumerate(weekdays):
        if word in working:
            today = now.astimezone(LOCAL_TZ).date()
            chosen = today + timedelta(days=(i - today.weekday()) % 7)
            result.update(date_from=chosen.isoformat(), date_to=chosen.isoformat())
            working = working.replace(word, " ")
    explicit = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if explicit:
        try:
            chosen = date.fromisoformat(explicit[1])
            result.update(date_from=chosen.isoformat(), date_to=chosen.isoformat())
            working = working.replace(normalize(explicit[1]), " ")
        except ValueError:
            raise QueryParseError(
                "Такой даты нет в календаре. Укажите дату, например 14.11.2026."
            ) from None
    numeric_date = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b", text)
    named_date = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{4}))?\b", text.lower()
    )
    human_date = numeric_date or named_date
    if human_date and not explicit:
        try:
            month = int(human_date[2]) if numeric_date else MONTHS[human_date[2]]
            year = (
                int(human_date[3]) if human_date[3] else now.astimezone(LOCAL_TZ).year
            )
            chosen = date(year, month, int(human_date[1]))
        except ValueError:
            raise QueryParseError(
                "Такой даты нет в календаре. Укажите дату, например 14.11.2026."
            ) from None
        result.update(date_from=chosen.isoformat(), date_to=chosen.isoformat())
        working = working.replace(normalize(human_date[0]), " ")
    stop = {
        "найди",
        "найти",
        "покажи",
        "показать",
        "куда",
        "пойти",
        "сходить",
        "интересного",
        "что",
        "есть",
        "мероприятия",
        "события",
        "мне",
        "для",
        "ребенком",
        "этот",
        "эти",
        "это",
        "все",
        "на",
        "до",
        "рублей",
        "руб",
        "лет",
        "год",
        "года",
        "цене",
        "ценой",
        "только",
        "пожалуйста",
        "а",
        "и",
        "в",
        "во",
        "с",
        "по",
        "к",
        "у",
    }
    result["q"] = " ".join(
        w for w in working.split() if w not in stop and not w.isdigit()
    )[:200]
    return result
