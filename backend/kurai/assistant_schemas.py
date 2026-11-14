"""Strict tool contracts; neither identity nor confirmation can come from a model."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import Category, EventOut, SubscriptionFilter


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=120)
    category: Category | None = None
    venue: str | None = Field(None, max_length=240)
    date_from: date | None = None
    date_to: date | None = None
    price_max: int | None = Field(None, ge=0, le=10_000_000)
    age: int | None = Field(None, ge=0, le=120)
    is_free: bool | None = None
    sort: Literal["date", "price"] | None = None
    more: bool = False

    @model_validator(mode="after")
    def date_order(self):
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("Invalid date range")
        return self


class EventArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID


class SimilarArgs(EventArgs):
    city: str | None = Field(None, max_length=120)


class VenueArgs(SearchArgs):
    venue: str = Field(min_length=1, max_length=240)


class SubscribeArgs(SubscriptionFilter):
    pass


class FeedbackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=10, max_length=2000)
    event_id: UUID | None = None


class ClarifyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["city", "date", "age", "location", "event", "scope"]


TOOL_TYPES = {
    "search_events": (
        SearchArgs,
        "Поиск. Аргументы — изменения текущих фильтров, пропущенное сохраняется; null удаляет условие. more=true — следующая страница. sort=price — дешевле. q — только название или содержательная тема, без слов запроса.",
    ),
    "get_event": (
        EventArgs,
        "Открыть событие: только UUID из last_events, никогда не придумывать ID.",
    ),
    "find_similar": (
        SimilarArgs,
        "Похожие события той же категории; только известный UUID.",
    ),
    "get_venue_schedule": (
        VenueArgs,
        "Расписание площадки. Точное название venue из справочника.",
    ),
    "subscribe": (
        SubscribeArgs,
        "Предложить подписку на новые события. Сохранение только отдельной кнопкой подтверждения.",
    ),
    "save_feedback": (
        FeedbackArgs,
        "Предложить отправку обращения модератору. Текст должен совпадать с сообщением пользователя. Отправка только отдельной кнопкой.",
    ),
    "ask_clarification": (
        ClarifyArgs,
        "Один необходимый вопрос: city — нет города; age — ребёнок без возраста; date — неясная дата; location — ближе без геоданных; event — неясная ссылка на событие; scope — запрос вне афиши.",
    ),
}


def tool_definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": cls.model_json_schema(),
            },
        }
        for name, (cls, desc) in TOOL_TYPES.items()
    ]


class AssistantInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=1000)


class ConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    accept: bool


class AssistantCard(BaseModel):
    event: EventOut
    reasons: list[str]


class PendingAction(BaseModel):
    token: str
    kind: Literal["subscribe", "save_feedback"]
    summary: str


class AssistantReply(BaseModel):
    request_id: str
    mode: Literal["model", "fallback", "confirmation"]
    message: str
    cards: list[AssistantCard] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    total: int = 0
    has_more: bool = False
    suggestions: list[str] = Field(default_factory=list)
    pending: PendingAction | None = None
