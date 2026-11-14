"""Opt-in live development evaluation, always in an isolated temporary database."""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from .assistant import AssistantService, PROMPT_VERSION
from .bot_controller import BotController
from .db import make_engine, session_factory
from .ingestion import import_rows
from .llm import NvidiaProvider
from .models import AssistantTrace, Event, Feedback, Subscription
from .subscriptions import owner_hash

ROOT = Path(__file__).resolve().parents[2]


def evaluate(output):
    suite_path = ROOT / "data/evaluation/assistant-smoke.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    provider = NvidiaProvider()
    if not provider.ready:
        raise SystemExit(
            "Для явного --live запуска нужны LLM_ENABLED=true, выбранная модель и NVIDIA_API_KEY в окружении."
        )
    reference = datetime.fromisoformat(suite["reference_time"])
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reference_time": reference.isoformat(),
        "scope": suite["scope"],
        "model": provider.settings.model,
        "prompt_version": PROMPT_VERSION,
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "corpus_sha256": {},
        "results": [],
    }
    (ROOT / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="assistant-evaluation-", dir=ROOT / "work"
    ) as temp:
        url = "sqlite:///" + (Path(temp) / "evaluation.db").as_posix()
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        config.attributes["ignore_database_env"] = True
        command.upgrade(config, "head")
        engine = make_engine(url)
        sessions = session_factory(engine)
        try:
            with sessions() as session:
                for filename in (
                    "data/reviewed-events.json",
                    "data/reviewed-events-extra.json",
                ):
                    content = (ROOT / filename).read_bytes()
                    report["corpus_sha256"][filename] = hashlib.sha256(
                        content
                    ).hexdigest()
                    result = import_rows(session, json.loads(content))
                    if result["rejected"]:
                        raise ValueError("Invalid evaluation corpus")
            agent = AssistantService(sessions, provider, lambda: reference)
            bot = BotController(sessions, lambda: reference, assistant=agent)
            for index, case in enumerate(suite["cases"]):
                original_provider = agent.provider
                if case.get("disable_model"):
                    agent.provider = NvidiaProvider()
                    agent.provider.settings = type(provider.settings)(enabled=False)
                try:
                    if case.get("surface") == "telegram-controller":
                        user_id = 8_000_000 + sum(ord(c) for c in case["dialog"])
                        result = bot.handle(user_id, text=case["text"])
                        owner = owner_hash("telegram", user_id)
                        with sessions() as session:
                            trace_row = session.scalar(
                                select(AssistantTrace)
                                .where(AssistantTrace.owner_hash == owner)
                                .order_by(AssistantTrace.created_at.desc())
                            )
                            trace = trace_row.details
                            ids = [
                                action[2:]
                                for row in result.buttons
                                for _, action in row
                                if action.startswith("e:")
                            ]
                            titles = [
                                session.get(Event, event_id).title for event_id in ids
                            ]
                        message, filters = result.text, trace.get("filters", {})
                        mode, pending = trace["mode"], None
                    else:
                        owner = owner_hash("web", case["dialog"])
                        result = agent.respond(owner, "web", case["text"])
                        with sessions() as session:
                            trace = session.get(
                                AssistantTrace, result.request_id
                            ).details
                        titles = [card.event.title for card in result.cards]
                        message, filters, mode = (
                            result.message,
                            result.filters,
                            result.mode,
                        )
                        pending = result.pending.kind if result.pending else None
                    tool = next(
                        (t["name"] for t in trace["tools"] if t["status"] == "ok"), None
                    )
                    checks = {"mode": mode == case.get("mode", "model")}
                    if "titles" in case:
                        checks["titles"] = sorted(titles) == sorted(case["titles"])
                    if "tool" in case:
                        checks["tool"] = tool == case["tool"]
                    for key, expected in case.get("filters", {}).items():
                        checks["filter_" + key] = filters.get(key) == expected
                    for key in ("question", "message"):
                        if key in case:
                            checks[key] = case[key] in message
                    if "pending" in case:
                        checks["pending"] = pending == case["pending"]
                    report["results"].append(
                        {
                            "id": case["id"],
                            "surface": case.get("surface", "shared-service"),
                            "passed": all(checks.values()),
                            "checks": checks,
                            "query": case["text"],
                            "mode": mode,
                            "tool": tool,
                            "titles": titles,
                            "message": message,
                            "filters": filters,
                            "pending": pending,
                            "trace": trace,
                        }
                    )
                finally:
                    agent.provider = original_provider
                output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    json.dumps(
                        {"case": case["id"], "passed": report["results"][-1]["passed"]},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            with sessions() as session:
                report["unconfirmed_mutations"] = len(
                    session.scalars(select(Subscription)).all()
                ) + len(session.scalars(select(Feedback)).all())
        finally:
            engine.dispose()
    durations = sorted(r["trace"]["duration_ms"] for r in report["results"])
    report["summary"] = {
        "passed": sum(r["passed"] for r in report["results"]),
        "total": len(report["results"]),
        "p95_ms": durations[math.ceil(len(durations) * 0.95) - 1],
        "cost_rub": 0,
        "final_acceptance": False,
    }
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report["summary"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "work/assistant-smoke.json"
    )
    args = parser.parse_args()
    print(json.dumps(evaluate(args.output), ensure_ascii=False))
