from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class PushSubscriptionIn(BaseModel):
    endpoint: HttpUrl
    keys: SubscriptionKeys


class UnsubscribeIn(BaseModel):
    endpoint: HttpUrl


class ScheduleOut(BaseModel):
    time: str
    status: str
    routes: list[str] = []
    updated_at: str | None = None
