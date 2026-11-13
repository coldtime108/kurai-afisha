"""Small deterministic search parser; no model and no invented event facts."""

import re
from datetime import date, timedelta
from difflib import get_close_matches
from .ingestion import normalize
from .catalog import LOCAL_TZ
from .schemas import CATEGORIES
from .subscriptions import period_bounds

CITIES = [
    "Уфа",
    "Стерлитамак",
    "Салават",
    "Нефтекамск",
    "Октябрьский",
    "Белорецк",
    "Туймазы",
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
}
WORDS = {
    "concert": ["концерт", "концерты", "музыка"],
    "theatre": ["театр", "спектакль", "балет", "опера"],
    "exhibition": ["выставка", "выставки"],
    "festival": ["фестиваль", "фестивали"],
    "cinema": ["кино", "кинопоказ"],
    "excursion": ["экскурсия", "экскурсии"],
}


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
    budget = re.search(r"до\s+(\d{1,7})(?:\s*(?:руб|₽))?", text.lower())
    if budget:
        result["price_max"] = int(budget[1])
        working = re.sub(r"до\s+\d+(?:\s+руб\w*)?", " ", working)
    if "бесплат" in working:
        result["is_free"] = True
        working = re.sub(r"бесплат\w*", " ", working)
    child = re.search(r"(?:реб[её]н\w*|дет\w*)\s+(\d{1,2})\s*(?:лет|год)", text.lower())
    if child and int(child[1]) <= 17:
        result["age"] = int(child[1])
        working = re.sub(r"(?:ребен\w*|дет\w*)\s+\d+\s+(?:лет|год\w*)", " ", working)
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
            pass
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
        "с",
        "по",
        "к",
        "у",
    }
    result["q"] = " ".join(
        w for w in working.split() if w not in stop and not w.isdigit()
    )[:200]
    return result
