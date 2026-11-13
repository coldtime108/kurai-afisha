from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class Category(str, Enum):
    concert = "concert"
    theatre = "theatre"
    exhibition = "exhibition"
    festival = "festival"
    cinema = "cinema"
    excursion = "excursion"
    other = "other"


CATEGORIES = {
    "concert": "Концерты",
    "theatre": "Театр",
    "exhibition": "Выставки",
    "festival": "Фестивали",
    "cinema": "Кино",
    "excursion": "Экскурсии",
    "other": "Другое",
}


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240)
    category: Category
    tags: list[str] = Field(default_factory=list, max_length=20)
    date_start: datetime
    date_end: datetime | None = None
    duration_min: int | None = Field(default=None, gt=0, le=1440)
    city: str = Field(min_length=1, max_length=120)
    venue: str = Field(min_length=1, max_length=240)
    address: str = Field(min_length=1, max_length=400)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    description: str = Field(min_length=1, max_length=6000)
    price_min: int | None = Field(default=None, ge=0, le=10000000)
    price_max: int | None = Field(default=None, ge=0, le=10000000)
    is_free: bool | None = None
    age_limit: int | None = Field(default=None)
    language: str | None = Field(default=None, max_length=80)
    org_link: HttpUrl | None = None
    source_url: HttpUrl
    source_type: Literal["manual", "import", "rss", "api", "page"] = "import"
    verified_at: datetime | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    status: Literal["published", "draft", "cancelled"] = "draft"

    @field_validator("date_start", "date_end", "verified_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Укажите часовой пояс даты, например +05:00")
        return value.astimezone(timezone.utc) if value else None

    @field_validator("age_limit")
    @classmethod
    def valid_age(cls, value):
        if value is not None and value not in (0, 6, 12, 16, 18):
            raise ValueError("Возраст: 0, 6, 12, 16 или 18")
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.date_end and self.date_end <= self.date_start:
            raise ValueError("Окончание должно быть позже начала")
        if (
            self.date_end
            and self.duration_min is not None
            and abs(
                (self.date_end - self.date_start).total_seconds() / 60
                - self.duration_min
            )
            > 1
        ):
            raise ValueError("Длительность противоречит времени окончания")
        if self.price_max is not None and (
            self.price_min is None or self.price_max < self.price_min
        ):
            raise ValueError("Проверьте диапазон цены")
        if self.is_free is True and (self.price_min != 0 or self.price_max != 0):
            raise ValueError("Для бесплатного входа обе цены должны быть равны 0")
        if self.is_free is False and self.price_min == 0 and self.price_max == 0:
            raise ValueError("Нулевая цена противоречит платному входу")
        if self.status == "published" and not self.verified_at:
            raise ValueError("Перед публикацией укажите время проверки источника")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Координаты задаются парой")
        return self


class EventOut(EventInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    normalized_title: str
    dedup_key: str
    source_hash: str
    sources: list[dict]
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class ImportBatch(BaseModel):
    rows: list[dict] = Field(max_length=1000)


class EventPageOut(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    size: int
    suggestions: list[str]


class StatusChange(BaseModel):
    status: Literal["published", "draft", "cancelled"]


class FeedbackInput(BaseModel):
    event_id: str | None = Field(default=None, max_length=36)
    message: str = Field(min_length=10, max_length=2000)
    website: str = Field(default="", max_length=200)


class SubscriptionFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    city: str = Field(min_length=1, max_length=120)
    category: Category | None = None
    period: Literal["week", "weekend"] = "week"


class SubscriptionInput(SubscriptionFilter):
    confirmed: Literal[True]


class SubscriptionOut(BaseModel):
    id: str
    filters: SubscriptionFilter
    expires_at: datetime


class EditEventInput(BaseModel):
    event: EventInput
    expected_updated_at: datetime

    @field_validator("expected_updated_at")
    @classmethod
    def version_aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Укажите часовой пояс версии карточки")
        return value.astimezone(timezone.utc)
