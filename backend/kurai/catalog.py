from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import func, or_, select
from .ingestion import normalize
from .models import Event

LOCAL_TZ = timezone(timedelta(hours=5))


def day_boundary(value: date, end=False):
    value = value + timedelta(days=1) if end else value
    return datetime.combine(value, time.min, LOCAL_TZ).astimezone(timezone.utc)


@dataclass
class Filters:
    q: str = ""
    city: str | None = None
    category: str | None = None
    venue: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    price_max: int | None = None
    age: int | None = None
    is_free: bool = False


def query_for(filters: Filters):
    query = select(Event).where(Event.status == "published")
    if filters.city:
        query = query.where(Event.city == filters.city)
    if filters.category:
        query = query.where(Event.category == filters.category)
    if filters.venue:
        query = query.where(Event.venue == filters.venue)
    if filters.date_from:
        query = query.where(Event.date_start >= day_boundary(filters.date_from))
    if filters.date_to:
        query = query.where(Event.date_start < day_boundary(filters.date_to, end=True))
    if filters.price_max is not None:
        query = query.where(
            Event.price_min.is_not(None), Event.price_min <= filters.price_max
        )
    if filters.age is not None:
        query = query.where(
            Event.age_limit.is_not(None), Event.age_limit <= filters.age
        )
    if filters.is_free:
        query = query.where(Event.is_free.is_(True))
    for word in normalize(filters.q).split():
        # Extract JSON scalars before lower(): SQLite may store Cyrillic as \u escapes.
        matches = [Event.normalized_title.contains(word, autoescape=True)]
        matches.extend(
            func.replace(func.lower(Event.tags[index].as_string()), "ё", "е").contains(
                word, autoescape=True
            )
            for index in range(20)
        )
        query = query.where(or_(*matches))
    return query


def search(session, filters: Filters, page=1, size=12, sort="date"):
    query = query_for(filters)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    order = (
        (Event.price_min.is_(None), Event.price_min, Event.date_start, Event.id)
        if sort == "price"
        else (Event.date_start, Event.id)
    )
    items = session.scalars(
        query.order_by(*order).offset((page - 1) * size).limit(size)
    ).all()
    suggestions = []
    if total == 0:
        for field, label in (
            ("price_max", "Увеличьте бюджет или уберите ограничение цены"),
            (
                "age",
                "Уточните возраст у организатора: часть событий не содержит возрастной маркировки",
            ),
            ("city", "Посмотрите события в других городах"),
            ("category", "Попробуйте другую категорию"),
            ("venue", "Посмотрите события на других площадках"),
            ("is_free", "Уберите условие бесплатного входа: в каталоге есть платные события"),
            ("q", "Попробуйте более короткое название"),
        ):
            value = getattr(filters, field)
            if value is not None and value != "" and not (field == "is_free" and not value):
                empty_value = "" if field == "q" else False if field == "is_free" else None
                relaxed = replace(filters, **{field: empty_value})
                if session.scalar(
                    select(func.count()).select_from(query_for(relaxed).subquery())
                ):
                    suggestions.append(label)
        if filters.date_from or filters.date_to:
            if session.scalar(
                select(func.count()).select_from(
                    query_for(replace(filters, date_from=None, date_to=None)).subquery()
                )
            ):
                suggestions.append("Расширьте диапазон дат")
        if not suggestions:
            suggestions.append(
                "В проверенном каталоге пока нет подходящих данных. Попробуйте другой город или период"
            )
    return items, total, suggestions
