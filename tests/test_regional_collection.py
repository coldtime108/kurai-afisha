from datetime import datetime

import pytest

from kurai.collection import sources
from kurai.schemas import EventInput
from kurai.seed import reviewed_rows
from kurai.source_adapters import links, parse_event


def source(identifier):
    return next(s for s in sources() if s["id"] == identifier)


def test_regional_organizer_uses_session_city_and_validated_venue():
    definition = source("ufakoncert")
    url = "https://ufakoncert.ru/event/example/"
    listing = f'<div class="events__item"><div class="events__name"><a href="{url}">Пример</a></div><div class="events__address"><a>Музыкальный колледж (Октябрьский)</a></div><span class="events__age">6+</span></div>'
    detail = '<div class="breadcrumbs">Главная &gt; Событие &gt; Концерт &gt; Пример</div><article class="new_ev"><h1>Пример</h1><div class="new_ev_s1_desc"><div>24/11/2026 , 19:00</div><div>Октябрьский</div><div>Музыкальный колледж (Октябрьский)</div><div>1 500 - 2 000 руб.</div></div></article>'
    assert links(definition, listing) == [url]
    payload, _ = parse_event(definition, url, detail, listing)
    validated = EventInput.model_validate(payload)
    assert validated.city == "Октябрьский" and validated.status == "draft"
    assert (validated.price_min, validated.price_max, validated.age_limit) == (
        1500,
        2000,
        6,
    )
    assert "Ленина" in validated.address
    with pytest.raises(ValueError):
        parse_event(
            definition,
            url,
            detail.replace("<div>Октябрьский</div>", "<div>Уфа</div>"),
            listing,
        )


def test_sibay_tour_does_not_become_local_session_or_guessed_year():
    definition = source("sibay")
    own = '<div class="date-row"><div class="date-row__when">24 НОЯБРЯ, 19:00</div><div class="date-row__place">Афиша · Большой зал</div><button class="js-open-ticket-modal" data-ticket-id="20261124-1900"></button></div>'
    tour = '<div class="date-row"><div class="date-row__when">25 НОЯБРЯ, 19:00 · РДК с. Зилаир</div><div class="date-row__place">Афиша · Большой зал</div><button class="js-open-ticket-modal" data-ticket-id="20261125-1900"></button></div>'
    detail = (
        '<h1>Проверочный концерт</h1><div class="detail-box__meta">6+ · 2 ч</div><p>от 600 ₽</p>'
        + own
        + tour
    )
    payload, _ = parse_event(
        definition, "https://sibay-concert.ru/afisha/example/", detail
    )
    assert (
        datetime.fromisoformat(payload["date_start"]).isoformat()
        == "2026-11-24T19:00:00+05:00"
    )
    assert payload["city"] == "Сибай" and payload["duration_min"] == 120
    assert payload["price_max"] is None and payload["is_free"] is False
    with pytest.raises(ValueError):
        parse_event(
            definition,
            "https://sibay-concert.ru/afisha/example/",
            detail.replace(own, ""),
        )


def test_kumertau_session_and_declared_city_coverage():
    definition = source("kumertau")
    url = "https://ufa.kassy.ru/events/teatr/2-99999/"
    listing = f'<li><a class="event_link" href="{url}">Спектакль</a><div class="RARS">16+</div><p class="venue">КТО Кумертау, 18 ноября 2026 19:00</p><div class="price_line">Билеты в наличии: 400 — 1 000</div></li>'
    detail = '<h1>Спектакль</h1><a href="/venue/mau-koncertno-teatralnoe-obedinenie-g-kumertau-212/">КТО Кумертау</a>'
    payload, _ = parse_event(definition, url, detail, listing)
    assert payload["city"] == "Кумертау" and payload["price_max"] == 1000
    configured = {city for s in sources() for city in s.get("cities", [s.get("city")])}
    assert {r["city"] for r in reviewed_rows()} <= configured
