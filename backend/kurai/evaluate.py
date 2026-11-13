"""Reproducible catalog baseline, isolated from the running site and Telegram."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from math import ceil
from pathlib import Path
import tempfile
from time import perf_counter

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from .bot_controller import BotController
from .catalog import LOCAL_TZ
from .ingestion import import_rows
from .main import create_app
from .models import Event

ROOT = Path(__file__).resolve().parents[2]


def key(item):
    title = item["title"] if isinstance(item, dict) else item.title
    start = item["date_start"] if isinstance(item, dict) else item.date_start
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return title + "@" + start.astimezone(LOCAL_TZ).date().isoformat()


def summarize(results):
    positives = [item for item in results if item["expected"]]
    durations = sorted(item["duration_ms"] for item in results)
    found = sum(bool(set(item["actual"]) & set(item["expected"])) for item in positives)
    false_empty = sum(not item["actual"] for item in positives)
    return {
        "cases": len(results),
        "exact_matches": sum(item["passed"] for item in results),
        "positive_cases": len(positives),
        "relevant_found_pct": round(100 * found / len(positives), 2) if positives else None,
        "false_empty_pct": round(100 * false_empty / len(positives), 2) if positives else None,
        "p95_ms": durations[ceil(len(durations) * .95) - 1] if durations else None,
    }


def evaluate():
    definitions = ROOT / "data/evaluation/search-baseline.json"
    suite = json.loads(definitions.read_text(encoding="utf-8"))
    corpus = ROOT / suite["corpus"]
    raw = corpus.read_bytes()
    rows = json.loads(raw)
    reference = datetime.fromisoformat(suite["reference_time"])
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="catalog-evaluation-", dir=work) as temporary:
        url = "sqlite:///" + (Path(temporary) / "evaluation.db").as_posix()
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        config.attributes["ignore_database_env"] = True
        command.upgrade(config, "head")
        application = create_app(url, admin_token="offline-evaluation-only")
        with application.state.sessions() as session:
            imported = import_rows(session, rows)
            if imported["rejected"]:
                raise ValueError("Evaluation corpus contains rejected records")
            events = session.scalars(select(Event)).all()
            by_id = {item.id: key(item) for item in events}
            duplicates = sum(
                count - 1 for count in Counter(item.dedup_key for item in events).values()
            )
        controller = BotController(application.state.sessions, clock=lambda: reference)
        with TestClient(application) as client:
            # Initialization is outside the measurement window.
            client.get("/health")
            for index, case in enumerate(suite["cases"]):
                started = perf_counter()
                if case["surface"] == "api":
                    response = client.get(
                        "/api/v1/events", params=case["filters"] | {"size": 50}
                    )
                    actual = [key(item) for item in response.json().get("items", [])]
                    message = ""
                    status = response.status_code
                else:
                    reply = controller.handle(900000 + index, text=case["text"])
                    actual = [
                        by_id[action[2:]]
                        for row in reply.buttons for _, action in row
                        if action.startswith("e:")
                    ]
                    message, status = reply.text, 200
                elapsed = round((perf_counter() - started) * 1000, 3)
                passed = (
                    status == 200 and set(actual) == set(case["expected"])
                    and len(actual) == len(set(actual))
                )
                if case.get("expected_message"):
                    passed = passed and case["expected_message"] in message
                results.append({
                    "id": case["id"], "surface": case["surface"],
                    "expected": case["expected"], "actual": actual,
                    "status": status, "duration_ms": elapsed, "passed": passed,
                })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_time": suite["reference_time"],
        "corpus_sha256": hashlib.sha256(raw).hexdigest(),
        "suite_sha256": hashlib.sha256(definitions.read_bytes()).hexdigest(),
        "event_count": len(events),
        "duplicate_key_count": duplicates,
        "known_price_count": sum(item.get("price_min") is not None for item in rows),
        "known_age_count": sum(item.get("age_limit") is not None for item in rows),
        "api": summarize([item for item in results if item["surface"] == "api"]),
        "bot": summarize([item for item in results if item["surface"] == "bot"]),
        "passed": all(item["passed"] for item in results),
        "measurement_scope": "In-process FastAPI TestClient and bot controller; SQLite; fixed reference date; seven reviewed sessions. Not production HTTP latency, LLM evaluation or independent acceptance.",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "api": report["api"], "bot": report["bot"]}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
