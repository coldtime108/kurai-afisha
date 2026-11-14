"""Small deterministic adapters for two official public event pages. No LLM."""

from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .catalog import LOCAL_TZ


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def all(self, tag=None, cls=None):
        return [
            n
            for n in self.walk()
            if (not tag or n.tag == tag)
            and (not cls or cls in n.attrs.get("class", "").split())
        ]

    def first(self, tag=None, cls=None):
        return next(iter(self.all(tag, cls)), None)

    def text(self):
        if self.tag in ("script", "style"):
            return ""
        return re.sub(
            r"\s+",
            " ",
            " ".join(c.text() if isinstance(c, Node) else c for c in self.children),
        ).strip()


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def text(node):
    return node.text() if node else ""


def links(source, html):
    if source["adapter"] in ("ufakoncert", "sibay", "kassy_venue"):
        from .regional_adapters import regional_links

        return regional_links(source, html)
    root = Tree(html).root
    if source["adapter"] == "bashgf":
        nodes = [n.first("a") for n in root.all(cls="entry-title")]
    else:
        nodes = root.all("a")
    result = []
    for node in nodes:
        if not node:
            continue
        url = urljoin(source["url"], node.attrs.get("href", "")).split("#")[0]
        parts = urlsplit(url)
        path_ok = (
            parts.path.startswith("/afisha/event/")
            if source["adapter"] == "bashgf"
            else bool(
                re.fullmatch(
                    r"/afisha/[a-z0-9-]+-\d{2}-\d{2}-\d{4}[a-z0-9-]*", parts.path
                )
            )
        )
        if (
            parts.scheme == "https"
            and parts.hostname in source["hosts"]
            and not parts.query
            and path_ok
            and url not in result
        ):
            result.append(url)
    return result[: source["max_events"]]


def age_limit(value):
    match = re.search(r"(?<!\d)(0|6|12|16|18)\s*\+", value)
    return int(match[1]) if match else None


def duration(value):
    match = re.search(
        r"[Пп]родолжительность\s*[:—-]?\s*(\d+)\s*(час\w*|мин\w*)(?:\s*(\d+)\s*мин\w*)?",
        value,
    )
    if not match:
        return None
    return int(match[1]) * (60 if match[2].startswith("час") else 1) + int(
        match[3] or 0
    )


def prices(value):
    # Only labelled numeric prices; never infer free admission from a missing price.
    match = re.search(
        r"(?:Цена|Стоимость(?: билетов| билета)?)\s*[:—-]?\s*(?:от\s*)?(\d[\d\s\u00a0]*)(?:\s*[-–—]\s*(\d[\d\s\u00a0]*))?\s*(?:₽|руб)",
        value,
        re.I,
    )
    if not match:
        return None, None
    lower = int(re.sub(r"\s", "", match[1]))
    upper = int(re.sub(r"\s", "", match[2])) if match[2] else None
    return lower, upper if upper is None or upper >= lower else None


def parse_event(source, url, html, listing_html=None):
    if source["adapter"] in ("ufakoncert", "sibay", "kassy_venue"):
        from .regional_adapters import parse_regional

        return parse_regional(source, url, html, listing_html)
    root = Tree(html).root
    issues = []
    if source["adapter"] == "bashgf":
        article = root.first("article")
        if not article:
            raise ValueError("Не найдена карточка филармонии")
        title = text(article.first(cls="entry-title"))
        stamp = article.first(cls="dtstart")
        if not stamp:
            raise ValueError("Источник не указал дату начала")
        start = datetime.fromisoformat(stamp.attrs["title"]).replace(tzinfo=LOCAL_TZ)
        finish = article.first(cls="dtend")
        end = (
            datetime.fromisoformat(finish.attrs["title"]).replace(tzinfo=LOCAL_TZ)
            if finish
            else None
        )
        if end and end <= start:
            end = None
        venue_name = text(article.first(cls="cat-links")).lower()
        hall = (
            "Малый зал"
            if "малый" in venue_name
            else "Большой зал" if "большой" in venue_name else None
        )
        venue = source["venue"] + (" · " + hall if hall else "")
        body = article.first(cls="my-poster-content")
        factual = text(body)
        price_block = article.first(cls="event-tickets")
        lower, upper = prices(text(price_block))
        if "бесплатно" in text(price_block).lower():
            # This plugin labels rental events 'free' when no price was entered.
            issues.append(
                "Надпись «Бесплатно» не подтверждена: цена оставлена неизвестной"
            )
        category = (
            "festival"
            if "фестивал" in title.lower()
            else "theatre" if "спектакл" in title.lower() else "concert"
        )
        org = next(
            (
                n.attrs.get("href")
                for n in article.all("a")
                if "Купить билет" in n.text()
            ),
            None,
        )
    else:
        article = root.first(cls="com-content-article")
        if not article:
            raise ValueError("Не найдена карточка театра")
        title = text(article.first("h2"))
        stamp = article.first("time")
        if not stamp or not stamp.attrs.get("datetime"):
            raise ValueError("Источник не указал дату начала")
        start = datetime.fromisoformat(stamp.attrs["datetime"])
        if start.tzinfo is None:
            raise ValueError("Дата театра без часового пояса")
        # Joomla retains technical creation seconds, while the public session time is HH:MM.
        start = start.replace(second=0, microsecond=0)
        path_date = re.search(r"(\d{2})-(\d{2})-(\d{4})(.*)$", urlsplit(url).path)
        if not path_date or start.astimezone(LOCAL_TZ).strftime("%d-%m-%Y") != "-".join(
            path_date.groups()[:3]
        ):
            raise ValueError("Дата карточки противоречит дате ссылки")
        if path_date[4]:
            raise ValueError(
                "Выездной спектакль: площадка и адрес требуют отдельной проверки"
            )
        end = None
        venue = source["venue"]
        factual = article.text()
        lower, upper = prices(factual)
        category = "theatre"
        org = next(
            (
                n.attrs.get("href")
                for n in article.all("a")
                if re.search(r"билет", n.text(), re.I)
                and n.attrs.get("href", "").startswith("http")
            ),
            None,
        )
    if not title or len(title) > 240:
        raise ValueError("Не распознано название")
    age = age_limit(factual)
    length = duration(factual)
    if length is None and source["adapter"] == "rusdram":
        for paragraph in article.all("p"):
            match = re.fullmatch(
                r"(?:(\d{1,2})\s*ч(?:аса|асов|ас)?\.?\s*)?(?:(\d{1,3})\s*мин(?:уты|ут|ута)?\.?)?",
                paragraph.text(),
                re.I,
            )
            if match and any(match.groups()):
                length = int(match[1] or 0) * 60 + int(match[2] or 0)
                break
    if age is None:
        issues.append("Возрастная маркировка не указана")
    if lower is None:
        issues.append("Цена не указана")
    if not length and not end:
        issues.append("Длительность не указана")
    # A short factual description avoids copying creative texts or artist biographies.
    description = f"{title}. {source['name']}. Дата и место взяты из официальной афиши. Подробности программы и наличие билетов — у организатора."
    cancelled = bool(
        re.search(
            r"\b(?:мероприятие|спектакль|концерт)\s+отмен[её]н[ао]?\b", factual, re.I
        )
    )
    if cancelled:
        issues.append("Источник сообщает об отмене")
    return {
        "title": title,
        "category": category,
        "tags": [],
        "date_start": start.isoformat(),
        "date_end": end.isoformat() if end else None,
        "duration_min": length,
        "city": source["city"],
        "venue": venue,
        "address": source["address"],
        "lat": None,
        "lon": None,
        "description": description,
        "price_min": lower,
        "price_max": upper,
        "is_free": False if lower and lower > 0 else None,
        "age_limit": age,
        "language": None,
        "org_link": org,
        "source_url": url,
        "source_type": "page",
        "verified_at": None,
        "confidence": 0.85 if age is not None and lower is not None else 0.7,
        "status": "cancelled" if cancelled else "draft",
    }, issues
