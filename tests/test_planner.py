"""A small set of planning checks; all generated events remain in the test database."""

from copy import deepcopy
from datetime import datetime, timezone
import json

from sqlalchemy import select

from kurai.assistant import AssistantService
from kurai.bot_controller import BotController
from kurai.ingestion import import_rows
from kurai.llm import LLMSettings
from kurai.models import Event, AssistantTrace
from kurai.planner import DayPlanInput, build_day_plan
from kurai.subscriptions import owner_hash

NOW = datetime(2026, 11, 14, 6, tzinfo=timezone.utc)


def prepare(app, rows, **second_changes):
    values = []
    for i, hour in enumerate((10, 13)):
        row = deepcopy(rows[0])
        row.update(
            title=f"Проверочное событие {i+1}",
            city="Стерлитамак",
            venue="Тестовая площадка",
            address="ул. Тестовая, 1",
            date_start=f"2026-11-15T{hour}:00:00+05:00",
            date_end=None,
            duration_min=60,
            price_min=100 if i == 0 else 300,
            price_max=200 if i == 0 else 400,
            is_free=False,
            age_limit=0,
            source_url=f"https://example.org/planner-fixture-{i}",
        )
        if i:
            row.update(second_changes)
        values.append(row)
    with app.state.sessions() as session:
        assert import_rows(session, values)["added"] == 2


def calculate(app, **changes):
    request = DayPlanInput.model_validate(
        {"city": "Стерлитамак", "day": "2026-11-15", "start_time": "09:00", **changes}
    )
    with app.state.sessions() as session:
        return build_day_plan(session, request, NOW)


def test_group_budget_uses_every_ticket_and_proposes_actual_minimum(app, rows):
    prepare(app, rows)
    result = calculate(app, adults=2, children_ages=[8], budget=1800)
    assert result.status == "ready" and len(result.routes[0].stops) == 2
    assert (result.routes[0].cost_min, result.routes[0].cost_max) == (1200, 1800)
    assert result.routes[0].stops[1].transfer_basis == "same_place"
    low = calculate(app, adults=2, children_ages=[8], budget=1700)
    assert low.status == "no_plan" and any("1800" in s for s in low.suggestions)
    relaxed = calculate(
        app, adults=2, children_ages=[8], budget=1700, allow_unconfirmed_cost=True
    )
    assert (
        relaxed.status == "provisional"
        and relaxed.routes[0].budget_status == "unconfirmed"
    )


def test_unknown_price_never_becomes_free_or_budget_confirmed(app, rows):
    prepare(app, rows, price_min=None, price_max=None, is_free=None)
    strict = calculate(app, budget=1000)
    assert strict.status == "no_plan"
    uncertain = calculate(app, budget=1000, allow_unconfirmed_cost=True)
    assert uncertain.status == "provisional" and uncertain.routes[0].cost_min is None
    assert uncertain.routes[0].budget_status == "unconfirmed"
    assert calculate(app).status == "provisional"


def test_age_duration_and_cancellation_are_not_silently_relaxed(app, rows):
    prepare(app, rows, age_limit=16)
    child = calculate(app, children_ages=[8])
    assert child.status == "no_plan" and child.diagnostics["age_restricted"] == 1
    with app.state.sessions() as session:
        event = session.scalar(
            select(Event).where(Event.title == "Проверочное событие 2")
        )
        event.age_limit, event.duration_min = 0, None
        session.commit()
    assert calculate(app).diagnostics["unknown_duration"] == 1
    with app.state.sessions() as session:
        event = session.scalar(
            select(Event).where(Event.title == "Проверочное событие 2")
        )
        event.duration_min, event.status = 60, "cancelled"
        session.commit()
    assert not calculate(app).routes


def test_transfer_requires_data_and_preserves_user_estimate_status(app, rows):
    prepare(app, rows, venue="Другая тестовая площадка", address="ул. Тестовая, 20")
    assert calculate(app).diagnostics["unknown_transfer"] == 1
    assert calculate(app, transfer_minutes=30, max_transfer_min=20).status == "no_plan"
    estimated = calculate(
        app, transfer_minutes=20, max_transfer_min=20, transfer_cost=50, budget=650
    )
    assert estimated.status == "provisional"
    assert (
        estimated.routes[0].cost_max == 650 and estimated.routes[0].transfer_cost == 50
    )
    assert estimated.routes[0].stops[1].transfer_basis == "user_estimate"


def test_time_overlap_includes_arrival_buffer(app, rows):
    prepare(app, rows)
    with app.state.sessions() as session:
        first = session.scalar(
            select(Event).where(Event.title == "Проверочное событие 1")
        )
        first.duration_min = 180
        session.commit()
    assert calculate(app).status == "no_plan"
    assert calculate(app, arrival_buffer_min=0).status == "ready"
    limited = calculate(app, arrival_buffer_min=0, end_time="13:30")
    assert limited.status == "no_plan"
    assert any("09:00–14:00" in text for text in limited.suggestions)


def test_telegram_planner_wizard_uses_same_result_without_model(app, rows):
    prepare(app, rows)
    bot = BotController(app.state.sessions, lambda: NOW)
    assert "шаг 1/6" in bot.handle(913, text="/plan").text
    bot.handle(913, callback="dp:city:0")
    bot.handle(913, callback="dp:day:2026-11-15")
    bot.handle(913, text="1 взрослый, дети 8")
    bot.handle(913, callback="dp:window:09:00-22:00")
    bot.handle(913, text="1200")
    result = bot.handle(913, callback="dp:move:same")
    assert (
        "Проверочное событие 1" in result.text
        and "Проверочное событие 2" in result.text
    )
    assert "800–1200 ₽" in result.text
    assert all(
        len(action.encode()) <= 64
        for row in result.buttons
        for _, action in row
        if not action.startswith("url:")
    )


def test_assistant_plan_tool_uses_group_budget_and_validated_ids(app, rows):
    prepare(app, rows)

    class Provider:
        ready = True
        settings = LLMSettings(enabled=True, api_key="offline-test")

        def complete(self, messages, tools, timeout):
            return {
                "calls": [
                    {
                        "id": "plan-test",
                        "type": "function",
                        "function": {
                            "name": "plan_day",
                            "arguments": json.dumps(
                                {
                                    "city": "Стерлитамак",
                                    "day": "2026-11-15",
                                    "start_time": "09:00",
                                    "adults": 1,
                                    "budget": 2000,
                                }
                            ),
                        },
                    }
                ],
                "finish_reason": "tool_calls",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }

    service = AssistantService(app.state.sessions, Provider(), lambda: NOW)
    reply = service.respond(
        owner_hash("web", "planner-test"),
        "web",
        "План в Стерлитамаке на 15 ноября 2026, 2 взрослых, до 1200 рублей",
    )
    assert reply.plan and reply.plan.people == 2 and reply.plan.input.budget == 1200
    assert reply.plan.status == "ready" and len(reply.cards) == 2
    with app.state.sessions() as session:
        trace = session.get(AssistantTrace, reply.request_id)
        assert trace.details["planner"]["input"]["adults"] == 2
