from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class PushSubscriptionIn(BaseModel):
    endpoint: HttpUrl
    keys: SubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_use_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Push subscription endpoints must use HTTPS.")
        return value


class UnsubscribeIn(BaseModel):
    endpoint: HttpUrl

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_use_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Push subscription endpoints must use HTTPS.")
        return value


class PushStatusIn(BaseModel):
    endpoint: HttpUrl

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_use_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Push subscription endpoints must use HTTPS.")
        return value


class PushTestIn(BaseModel):
    endpoint: HttpUrl

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_use_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Push subscription endpoints must use HTTPS.")
        return value


class ScheduleOut(BaseModel):
    time: str
    status: Literal["waiting", "available", "no_schedule", "error"]
    routes: list[str] = Field(default_factory=list)
    updated_at: str | None = None
    error: str | None = None
