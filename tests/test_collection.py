"""Small checks of collection behaviour. Fixtures contain only short factual markup."""

from datetime import datetime, timezone
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import func, select

from kurai.collection import CollectionService, RobotRules, sources, validate_url
from kurai.models import CollectedItem, CollectionRun, Event, SourcePage
from kurai.source_adapters import parse_event

NOW = datetime(2026, 11, 14, 6, tzinfo=timezone.utc)
GF = "https://bashgf.ru/afisha/event/jubilejnyj-koncert-azamata-hasanshina/"
THEATRE = "https://rusdramteatr.ru/afisha/tsarevna-lyagushka-15-11-2026"
GF_DETAIL = """<article><h3 class="entry-title">Освобождение звука</h3>
<abbr class="dtstart" title="2026-11-14 18:00"></abbr><abbr class="dtend" title="2026-11-14 18:00"></abbr>
<span class="cat-links">Рубрики: Малый (органный) зал</span><div class="event-tickets">Цена: 600 - 800 ₽</div>
<div class="my-poster-content">Программа концерта. 6+</div></article>"""
THEATRE_DETAIL = """<div class="com-content-article"><time datetime="2026-11-15T12:00:00+05:00"></time>
<h2>Царевна - Лягушка</h2><h5>0+</h5><p>Для детей</p></div>"""


class FixtureClient:
    def __init__(self, source, pages):
        self.source, self.pages = source, pages

    def load_robots(self):
        pass

    def close(self):
        pass

    def fetch(self, url):
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


def collector(app):
    definitions = sources()
    pages = {
        definitions[0][
            "url"
        ]: f'<h3 class="entry-title"><a href="{GF}">Концерт</a></h3>',
        definitions[1]["url"]: f'<a href="{THEATRE}">Спектакль</a>',
        GF: GF_DETAIL,
        THEATRE: THEATRE_DETAIL,
    }
    service = CollectionService(
        app.state.sessions,
        definitions,
        lambda source: FixtureClient(source, pages),
        lambda: NOW,
    )
    return service, pages


def test_two_sources_go_to_drafts_and_repeat_does_not_create_copies(app):
    service, _ = collector(app)
    first = service.run()
    second = service.run()
    with app.state.sessions() as session:
        assert session.get(CollectionRun, first).status == "complete"
        assert sum(r["added"] for r in session.get(CollectionRun, first).summary) == 2
        assert (
            sum(r["unchanged"] for r in session.get(CollectionRun, second).summary) == 2
        )
        events = session.scalars(select(Event)).all()
        assert len(events) == 2 and all(e.status == "draft" for e in events)
        assert session.scalar(select(func.count()).select_from(SourcePage)) == 4
        concert = next(e for e in events if e.category == "concert")
        assert (
            concert.price_min == 600
            and concert.price_max == 800
            and concert.date_end is None
        )
        child = next(e for e in events if e.category == "theatre")
        assert (
            child.age_limit == 0 and child.price_min is None and child.is_free is None
        )


def test_reschedule_is_a_proposal_with_same_id_and_cancellation_hides_event(app):
    service, pages = collector(app)
    service.run()
    with app.state.sessions() as session:
        event = session.scalar(select(Event).where(Event.source_url == GF))
        identifier, original_date = event.id, event.date_start
        event.status, event.verified_at = "published", NOW
        session.commit()
    pages[GF] = GF_DETAIL.replace("2026-11-14", "2026-11-16")
    service.run()
    with app.state.sessions() as session:
        event = session.get(Event, identifier)
        assert event.date_start == original_date and event.status == "published"
        record = session.scalar(
            select(CollectedItem).where(CollectedItem.external_id == GF)
        )
        assert record.event_id == identifier and record.reviewed_hash is None
        assert "2026-11-16" in record.payload["date_start"]
        assert session.scalar(select(func.count()).select_from(Event)) == 2
    pages[GF] = pages[GF].replace("Программа концерта.", "Концерт отменён.")
    service.run()
    with app.state.sessions() as session:
        assert session.get(Event, identifier).status == "cancelled"


def test_one_unavailable_source_does_not_stop_other(app):
    service, pages = collector(app)
    pages[GF] = httpx.ReadTimeout("offline fixture")
    identifier = service.run()
    with app.state.sessions() as session:
        result = session.get(CollectionRun, identifier)
        assert result.status == "partial" and result.summary[0]["errors"]
        assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_source_url_boundaries_and_unknown_free_label():
    source = sources()[0]
    for url in (
        "https://127.0.0.1/afisha/",
        "https://bashgf.ru.evil.example/afisha/",
        "https://bashgf.ru/afisha/?url=http://localhost",
        "https://bashgf.ru/wp-admin/",
        "http://bashgf.ru/afisha/",
    ):
        with pytest.raises(ValueError):
            validate_url(source, url, resolve=False)
    payload, issues = parse_event(
        source, GF, GF_DETAIL.replace("Цена: 600 - 800 ₽", "Бесплатно")
    )
    assert payload["is_free"] is None and payload["price_min"] is None
    assert any("не подтверждена" in message for message in issues)


def test_collection_routes_are_private_and_review_receipt_is_versioned(app, admin):
    service, _ = collector(app)
    app.state.collection = service
    # The HTTP read/review contracts use only the common database.
    service.run()
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/collection").status_code == 401
        result = client.get("/api/v1/admin/collection/items", headers=admin).json()
        assert len(result) == 2
        item = result[0]
        path = f"/api/v1/admin/collection/items/{item['id']}/reviewed"
        assert (
            client.post(path, headers=admin, json={"fingerprint": "0" * 64}).status_code
            == 409
        )
        assert (
            client.post(
                path, headers=admin, json={"fingerprint": item["fingerprint"]}
            ).status_code
            == 200
        )


def test_robots_query_rule_does_not_block_entire_site():
    rules = RobotRules(
        "User-agent: *\r\r\nDisallow: /?\r\r\nDisallow: /wp-\nDisallow: */feed\nAllow: /wp-content/uploads/"
    )
    assert rules.can_fetch("KuraiAfisha", "https://bashgf.ru/afisha/")
    assert not rules.can_fetch("KuraiAfisha", "https://bashgf.ru/?s=test")
    assert not rules.can_fetch("KuraiAfisha", "https://bashgf.ru/afisha/feed")
    assert not rules.can_fetch("KuraiAfisha", "https://bashgf.ru/wp-admin/")
    assert rules.can_fetch("KuraiAfisha", "https://bashgf.ru/wp-content/uploads/a.jpg")
