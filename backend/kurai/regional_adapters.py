"""Regional listings: explicit venues and session dates, never an artist's home city."""

from datetime import datetime
import re
from urllib.parse import urljoin, urlsplit

from .catalog import LOCAL_TZ
from .query_parser import MONTHS
from .source_adapters import Tree, text, age_limit


def regional_links(source, html):
    root = Tree(html).root
    urls = []
    if source["adapter"] == "ufakoncert":
        for card in root.all(cls="events__item"):
            address = card.first(cls="events__address")
            if text(address.first("a") if address else None) in source["venues"]:
                link = card.first(cls="events__name")
                if link and link.first("a"):
                    urls.append(link.first("a").attrs.get("href", ""))
    elif source["adapter"] == "sibay":
        for card in root.all("article", cls="event-card"):
            match = re.fullmatch(
                r"location\.href='(https://[^']+)';?", card.attrs.get("onclick", "")
            )
            if match:
                urls.append(match[1])
    else:
        urls = [a.attrs.get("href", "") for a in root.all(cls="event_link")]
    result = []
    for value in urls:
        url = urljoin(source["url"], value)
        parts = urlsplit(url)
        prefixes = {
            "ufakoncert": ("/event/",),
            "sibay": ("/afisha/", "/detskij-teatr-sulpan-2/"),
            "kassy_venue": ("/events/",),
        }[source["adapter"]]
        if (
            parts.scheme == "https"
            and parts.hostname in source["hosts"]
            and not parts.query
            and not parts.fragment
            and parts.path.startswith(prefixes)
            and url not in result
        ):
            result.append(url)
    return result[: source["max_events"]]


def money_range(value):
    amounts = [
        int(re.sub(r"\s", "", number))
        for number in re.findall(r"\d[\d\s\u00a0]*", value)
    ]
    if len(amounts) not in (1, 2):
        return None, None
    return amounts[0], amounts[-1]


def parse_regional(source, url, html, listing_html):
    root, listing = Tree(html).root, Tree(listing_html or "").root
    issues = []
    cancelled_hint = False
    title = text(root.first("h1"))
    lower = upper = age = length = None
    if source["adapter"] == "ufakoncert":
        block = root.first(cls="new_ev_s1_desc")
        values = [n.text() for n in block.all("div")] if block else []
        if len(values) < 4:
            raise ValueError("Не распознаны дата, город и площадка организатора")
        match = re.fullmatch(r"(\d{2}/\d{2}/\d{4})\s*,\s*(\d{2}:\d{2})", values[0])
        if not match:
            raise ValueError("Не распознана точная дата сеанса")
        start = datetime.strptime(match[1] + " " + match[2], "%d/%m/%Y %H:%M").replace(
            tzinfo=LOCAL_TZ
        )
        venue = values[2]
        location = source["venues"].get(venue)
        if not location or values[1] != location["city"]:
            raise ValueError("Площадка или город требуют отдельной проверки")
        city, address = location["city"], location["address"]
        lower, upper = money_range(values[3])
        card = next(
            (
                n
                for n in listing.all(cls="events__item")
                if any(
                    urljoin(source["url"], a.attrs.get("href", "")) == url
                    for a in n.all("a")
                )
            ),
            None,
        )
        if not card:
            raise ValueError("Сеанс отсутствует в загруженной афише")
        age = age_limit(text(card.first(cls="events__age")))
        breadcrumb = next(
            (n.text() for n in root.walk() if "bread" in n.attrs.get("class", "")), ""
        )
        genre = breadcrumb.split(">")[2].strip() if breadcrumb.count(">") >= 2 else ""
        category = {
            "Концерт": "concert",
            "Театр": "theatre",
            "Балет": "theatre",
            "Шоу": "other",
            "Фестивали": "festival",
        }.get(genre, "other")
        factual = text(root.first(cls="new_ev"))
    elif source["adapter"] == "sibay":
        own_rows = []
        for row in root.all(cls="date-row"):
            when, place = text(row.first(cls="date-row__when")), text(
                row.first(cls="date-row__place")
            )
            if ("·" in when and "Сибайское КТО" not in when) or not re.search(
                r"Большой зал|Малый зал", place
            ):
                continue
            button = row.first("button", cls="js-open-ticket-modal")
            identifier = button.attrs.get("data-ticket-id", "") if button else ""
            if re.fullmatch(r"\d{8}-\d{4}", identifier):
                own_rows.append((row, identifier))
        if len(own_rows) != 1:
            raise ValueError(
                "Нет единственного сеанса на собственной площадке: гастроли или несколько дат требуют сверки"
            )
        row, identifier = own_rows[0]
        cancelled_hint = "отмен" in text(row.first(cls="date-row__status")).lower()
        start = datetime.strptime(identifier, "%Y%m%d-%H%M").replace(tzinfo=LOCAL_TZ)
        city, venue, address = source["city"], source["venue"], source["address"]
        hall = (
            "Малый зал"
            if "Малый зал" in text(row.first(cls="date-row__place"))
            else "Большой зал"
        )
        venue += " · " + hall
        meta = text(root.first(cls="detail-box__meta"))
        age = age_limit(meta)
        hours, minutes = re.search(r"(\d+)\s*ч", meta), re.search(r"(\d+)\s*мин", meta)
        length = (
            int(hours[1]) * 60 + (int(minutes[1]) if minutes else 0)
            if hours
            else int(minutes[1]) if minutes else None
        )
        match = re.search(r"от\s+(\d[\d\s\u00a0]*)\s*₽", root.text())
        lower = int(re.sub(r"\s", "", match[1])) if match else None
        category = "theatre" if "/detskij-teatr-" in url else "concert"
        factual = title + " " + row.text()
    else:
        card = next(
            (
                n
                for n in listing.all("li")
                if n.first(cls="event_link")
                and urljoin(
                    source["url"], n.first(cls="event_link").attrs.get("href", "")
                )
                == url
            ),
            None,
        )
        if not card:
            raise ValueError("Не найден сеанс в афише площадки")
        venue_path = urlsplit(source["url"]).path
        if not any(a.attrs.get("href") == venue_path for a in root.all("a")):
            raise ValueError("Карточка не подтверждает площадку сеанса")
        match = re.search(
            r"(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{2}):(\d{2})",
            text(card.first(cls="venue")).lower(),
        )
        if not match or match[2] not in MONTHS:
            raise ValueError("Не распознана дата сеанса площадки")
        start = datetime(
            int(match[3]),
            MONTHS[match[2]],
            int(match[1]),
            int(match[4]),
            int(match[5]),
            tzinfo=LOCAL_TZ,
        )
        title = text(card.first(cls="event_link"))
        city, venue, address = source["city"], source["venue"], source["address"]
        lower, upper = money_range(text(card.first(cls="price_line")))
        age = age_limit(text(card.first(cls="RARS")))
        category = (
            "theatre"
            if "/teatr/" in url
            else "concert" if "/koncert" in url else "other"
        )
        factual = card.text()
    if not title or len(title) > 240:
        raise ValueError("Не распознано название события")
    if lower is None:
        issues.append("Цена не указана")
    if age is None:
        issues.append("Возрастная маркировка не указана")
    if length is None:
        issues.append("Длительность не указана")
    cancelled = cancelled_hint or bool(
        re.search(
            r"(?:мероприятие|концерт|спектакль)\s+отмен[её]н[ао]?|сеанс\s+отмен[её]н",
            factual,
            re.I,
        )
    )
    return {
        "title": title,
        "category": category,
        "tags": [],
        "date_start": start.isoformat(),
        "date_end": None,
        "duration_min": length,
        "city": city,
        "venue": venue,
        "address": address,
        "lat": None,
        "lon": None,
        "description": f"{title}. {venue}, {city}. Сведения из афиши источника; наличие билетов уточняйте у организатора.",
        "price_min": lower,
        "price_max": upper,
        "is_free": False if lower and lower > 0 else None,
        "age_limit": age,
        "language": None,
        "org_link": url,
        "source_url": url,
        "source_type": "page",
        "verified_at": None,
        "confidence": 0.85 if lower is not None and age is not None else 0.7,
        "status": "cancelled" if cancelled else "draft",
    }, issues
