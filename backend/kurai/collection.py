"""Source collection into drafts and proposals; published data is never blindly replaced."""

import argparse
import asyncio
from datetime import datetime, timedelta
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
from threading import Lock
import time
from urllib.parse import urljoin, urlsplit
import re

import httpx
from sqlalchemy import delete, select

from .db import make_engine, session_factory
from .ingestion import import_rows, normalize, sha
from .models import AuditEntry, CollectedItem, CollectionRun, Event, SourcePage, utcnow
from .schemas import EventInput
from .source_adapters import links, parse_event

ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "KuraiAfisha/0.3 (+https://github.com/coldtime108/kurai-afisha)"


class RobotRules:
    """Longest matching rule, * wildcard and $ end marker; queries remain literal."""

    def __init__(self, content, agent="KuraiAfisha"):
        groups, agents, rules = [], [], []
        for line in content.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if key.lower() == "user-agent":
                if rules:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
            elif key.lower() in ("allow", "disallow") and agents and value:
                rules.append((key.lower() == "allow", value))
        groups.append((agents, rules))
        matches = [
            (
                max(
                    (
                        0 if token == "*" else len(token)
                        for token in names
                        if token == "*" or token in agent.lower()
                    ),
                    default=-1,
                ),
                group,
            )
            for names, group in groups
        ]
        best = max((score for score, _ in matches), default=-1)
        self.rules = [
            rule
            for score, group in matches
            if score == best and score >= 0
            for rule in group
        ]

    def can_fetch(self, agent, url):
        parsed = urlsplit(url)
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
        matches = []
        for allowed, pattern in self.rules:
            ending = pattern.endswith("$")
            body = pattern[:-1] if ending else pattern
            expression = (
                "^" + re.escape(body).replace(r"\*", ".*") + ("$" if ending else "")
            )
            if re.search(expression, target):
                matches.append((len(body.replace("*", "")), allowed))
        return max(matches)[1] if matches else True


def sources():
    return json.loads(
        (ROOT / "data/collection-sources.json").read_text(encoding="utf-8")
    )


def validate_url(source, url, resolve=True):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in source["hosts"]
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not (
            parsed.path.startswith(source["path_prefix"])
            or parsed.path == "/robots.txt"
        )
    ):
        raise ValueError("Ссылка вне разрешённого источника")
    if resolve:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_global for row in addresses
        ):
            raise ValueError("Недопустимый сетевой адрес источника")


class SourceClient:
    def __init__(self, source):
        self.source = source
        self.client = httpx.Client(
            timeout=httpx.Timeout(10, connect=5),
            follow_redirects=False,
            trust_env=source.get("use_system_proxy", False),
            headers={"User-Agent": USER_AGENT},
        )
        self.last_request = 0
        self.robots = None

    def close(self):
        self.client.close()

    def fetch(self, url):
        started = time.monotonic()
        for _ in range(4):
            validate_url(self.source, url)
            if (
                self.robots
                and urlsplit(url).path != "/robots.txt"
                and not self.robots.can_fetch("KuraiAfisha", url)
            ):
                raise ValueError("Загрузка запрещена robots.txt")
            delay = 0.35 - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            with self.client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                if not any(
                    t in response.headers.get("content-type", "")
                    for t in ("text/html", "text/plain")
                ):
                    raise ValueError("Источник вернул неподдерживаемый формат")
                content = bytearray()
                for part in response.iter_bytes():
                    content.extend(part)
                    if len(content) > 2_000_000 or time.monotonic() - started > 20:
                        raise ValueError("Превышен размер или время загрузки источника")
                return bytes(content).decode("utf-8-sig", errors="replace")
        raise ValueError("Слишком много перенаправлений")

    def load_robots(self):
        parsed = urlsplit(self.source["url"])
        url = f"https://{parsed.netloc}/robots.txt"
        try:
            content = self.fetch(url)
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (404, 410):
                return
            raise
        if "<html" in content.lower():
            raise ValueError("robots.txt вернул HTML вместо правил")
        self.robots = RobotRules(content)


class CollectionService:
    def __init__(
        self, sessions, definitions=None, fetcher_factory=SourceClient, clock=utcnow
    ):
        self.sessions = sessions
        self.definitions = definitions if definitions is not None else sources()
        self.fetcher_factory, self.clock = fetcher_factory, clock
        self.lock = Lock()

    def snapshot(self, source_id, url, html):
        content = html.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        with self.sessions() as session:
            page = session.scalar(
                select(SourcePage).where(
                    SourcePage.url == url, SourcePage.content_hash == digest
                )
            )
            if page:
                page.fetched_at = self.clock()
            else:
                session.add(
                    SourcePage(
                        source_id=source_id,
                        url=url,
                        content_hash=digest,
                        body_gzip=gzip.compress(content),
                        fetched_at=self.clock(),
                    )
                )
            session.commit()

    def store(self, source, url, payload, issues):
        now = self.clock()
        validated = EventInput.model_validate(payload)
        fingerprint = sha(payload)
        with self.sessions() as session:
            record = session.scalar(
                select(CollectedItem).where(
                    CollectedItem.source_id == source["id"],
                    CollectedItem.external_id == url,
                )
            )
            unchanged = bool(record and record.fingerprint == fingerprint)
            if unchanged and record.reviewed_hash == fingerprint:
                record.last_seen_at = now
                session.commit()
                return "unchanged"
            event = (
                session.get(Event, record.event_id)
                if record and record.event_id
                else None
            )
            if event is None:
                # Source identity/date is stronger than cosmetic title changes during initial linking.
                event = session.scalar(
                    select(Event).where(
                        Event.source_url == url,
                        Event.date_start == validated.date_start,
                    )
                )
            if event is None:
                key = sha(
                    [
                        normalize(validated.title),
                        validated.model_dump(mode="json")["date_start"],
                        normalize(validated.city),
                        normalize(validated.venue),
                    ]
                )
                event = session.scalar(select(Event).where(Event.dedup_key == key))
            outcome = "unchanged" if unchanged else "matched"
            if event is None:
                result = import_rows(
                    session, [payload], actor="collector:" + source["id"]
                )
                if result["rejected"]:
                    raise ValueError(result["errors"][0]["reason"])
                event = session.scalar(
                    select(Event).where(Event.source_hash == sha(payload))
                )
                outcome = "added"
            proposed = []
            if outcome != "added":
                for field in (
                    "title",
                    "category",
                    "date_start",
                    "date_end",
                    "duration_min",
                    "city",
                    "venue",
                    "address",
                    "price_min",
                    "price_max",
                    "age_limit",
                ):
                    new, old = getattr(validated, field), getattr(event, field)
                    if new is None:
                        continue  # Unknown source fields never erase known reviewed facts.
                    if field == "address":
                        city = normalize(validated.city)
                        if (
                            normalize(str(new)).removeprefix(city).strip()
                            == normalize(str(old)).removeprefix(city).strip()
                        ):
                            continue
                    if field in ("title", "venue", "address") and normalize(
                        str(new)
                    ) == normalize(str(old)):
                        continue
                    if new != old:
                        proposed.append(field)
                if validated.status == "cancelled" and event.status != "cancelled":
                    proposed.append("status")
                if proposed:
                    outcome = "unchanged" if unchanged else "proposals"
                    # A clear cancellation removes the event from search immediately.
                    if "status" in proposed:
                        before = event.status
                        event.status = "cancelled"
                        session.add(
                            AuditEntry(
                                actor="collector:" + source["id"],
                                action="source_cancelled",
                                entity_id=event.id,
                                changes={"before": before, "source_url": url},
                            )
                        )
                    if not unchanged:
                        session.add(
                            AuditEntry(
                                actor="collector:" + source["id"],
                                action="collection_proposal",
                                entity_id=event.id,
                                changes={
                                    "fields": proposed,
                                    "proposed": payload,
                                    "source_url": url,
                                },
                            )
                        )
            if record is None:
                record = CollectedItem(
                    source_id=source["id"],
                    external_id=url,
                    event_id=event.id,
                    payload=payload,
                    issues=[],
                    fingerprint=fingerprint,
                )
                session.add(record)
            record.payload, record.fingerprint, record.last_seen_at = (
                payload,
                fingerprint,
                now,
            )
            record.event_id = event.id
            record.issues = issues + (
                ["Источник предлагает изменения: " + ", ".join(proposed)]
                if proposed
                else []
            )
            if not proposed and event.status != "draft" and event.verified_at:
                record.reviewed_hash = fingerprint
            elif event.status == "draft" or proposed:
                record.reviewed_hash = None
            session.commit()
            return outcome

    def run(self, identifier=None, reserved=False):
        if not reserved and not self.lock.acquire(blocking=False):
            return None
        try:
            with self.sessions() as session:
                # Runs interrupted by a previous process do not remain perpetually 'running'.
                for old in session.scalars(
                    select(CollectionRun).where(CollectionRun.status == "running")
                ):
                    old.status, old.finished_at = "interrupted", self.clock()
                job = session.get(CollectionRun, identifier) if identifier else None
                if job is None:
                    job = CollectionRun(
                        status="running", summary=[], started_at=self.clock()
                    )
                    session.add(job)
                else:
                    job.status = "running"
                session.commit()
                identifier = job.id
            summaries = []
            deadline = time.monotonic() + 180
            for source in self.definitions:
                result = dict(
                    source_id=source["id"],
                    name=source["name"],
                    found=0,
                    added=0,
                    matched=0,
                    proposals=0,
                    unchanged=0,
                    past=0,
                    errors=[],
                )
                client = self.fetcher_factory(source)
                try:
                    client.load_robots()
                    html = client.fetch(source["url"])
                    self.snapshot(source["id"], source["url"], html)
                    urls = links(source, html)
                    if not urls:
                        raise ValueError(
                            "Афиша не содержит распознанных ссылок; возможно, изменилась разметка"
                        )
                    result["found"] = len(urls)
                    for url in urls:
                        if time.monotonic() > deadline:
                            result["errors"].append(
                                {
                                    "url": url,
                                    "message": "Достигнут предел времени сбора",
                                }
                            )
                            break
                        try:
                            html = client.fetch(url)
                            self.snapshot(source["id"], url, html)
                            payload, issues = parse_event(source, url, html)
                            if (
                                datetime.fromisoformat(payload["date_start"])
                                <= self.clock()
                            ):
                                result["past"] += 1
                                continue
                            result[self.store(source, url, payload, issues)] += 1
                        except (
                            httpx.HTTPError,
                            ValueError,
                            KeyError,
                            socket.gaierror,
                        ) as error:
                            result["errors"].append(
                                {
                                    "url": url,
                                    "message": (
                                        str(error)[:300]
                                        if isinstance(error, ValueError)
                                        else type(error).__name__
                                    ),
                                }
                            )
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    socket.gaierror,
                ) as error:
                    result["errors"].append(
                        {
                            "url": source["url"],
                            "message": (
                                str(error)[:300]
                                if isinstance(error, ValueError)
                                else type(error).__name__
                            ),
                        }
                    )
                finally:
                    client.close()
                summaries.append(result)
                with self.sessions() as session:
                    job = session.get(CollectionRun, identifier)
                    job.summary = list(summaries)
                    session.commit()
            with self.sessions() as session:
                job = session.get(CollectionRun, identifier)
                job.status = (
                    "partial" if any(r["errors"] for r in summaries) else "complete"
                )
                job.finished_at = self.clock()
                session.execute(
                    delete(SourcePage).where(
                        SourcePage.fetched_at < self.clock() - timedelta(days=7)
                    )
                )
                session.execute(
                    delete(CollectionRun).where(
                        CollectionRun.started_at < self.clock() - timedelta(days=30)
                    )
                )
                session.commit()
            return identifier
        except Exception:
            if identifier:
                with self.sessions() as session:
                    job = session.get(CollectionRun, identifier)
                    job.status, job.finished_at = "failed", self.clock()
                    session.commit()
            raise
        finally:
            self.lock.release()

    async def schedule(self):
        with self.sessions() as session:
            for old in session.scalars(
                select(CollectionRun).where(
                    CollectionRun.status.in_(["running", "pending"])
                )
            ):
                old.status, old.finished_at = "interrupted", self.clock()
            session.commit()
        while True:
            if os.getenv("COLLECTION_ENABLED", "false").lower() == "true":
                with self.sessions() as session:
                    last = session.scalar(
                        select(CollectionRun)
                        .order_by(CollectionRun.started_at.desc())
                        .limit(1)
                    )
                    due = last is None or last.started_at < self.clock() - timedelta(
                        hours=6
                    )
                if due:
                    try:
                        await asyncio.to_thread(self.run)
                    except Exception:
                        pass  # The persisted run contains the failure; catalog remains available.
            await asyncio.sleep(60)


def main():
    parser = argparse.ArgumentParser(
        description="Собрать официальные афиши в черновики"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    engine = make_engine()
    try:
        service = CollectionService(session_factory(engine))
        identifier = service.run()
        with service.sessions() as session:
            run = session.get(CollectionRun, identifier)
            report = {
                "id": run.id,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat(),
                "sources": run.summary,
            }
        if args.output:
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
