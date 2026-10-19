from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Column, MetaData, String, Table, Text, create_engine, inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url


metadata = MetaData()
schedule_state = Table(
    "schedule_state", metadata,
    Column("schedule_date", String(10), primary_key=True),
    Column("schedule_time", String(8), primary_key=True),
    Column("schedule_hash", String(64)),
    Column("normalized_schedule", Text),
    Column("first_detected_at", String(40)),
    Column("last_checked_at", String(40), nullable=False),
    Column("notification_status", String(32), nullable=False, default="not_sent"),
    Column("result_status", String(20), nullable=False, default="waiting"),
    Column("last_error", Text),
)
push_subscriptions = Table(
    "push_subscriptions", metadata,
    Column("endpoint", Text, primary_key=True),
    Column("p256dh", Text, nullable=False),
    Column("auth", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """Small SQLAlchemy repository that works with local SQLite and PostgreSQL."""

    def __init__(self, database: Path | str):
        if isinstance(database, Path):
            database.parent.mkdir(parents=True, exist_ok=True)
            database_url = f"sqlite:///{database.as_posix()}"
        else:
            database_url = database
        parsed_url = make_url(database_url)
        is_sqlite = parsed_url.get_backend_name() == "sqlite"
        if is_sqlite and parsed_url.database and parsed_url.database != ":memory:":
            Path(parsed_url.database).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        self.engine: Engine = create_engine(database_url, connect_args=connect_args, future=True)
        metadata.create_all(self.engine)
        self._migrate_schedule_state()

    def _migrate_schedule_state(self) -> None:
        columns = {column["name"] for column in inspect(self.engine).get_columns("schedule_state")}
        with self.engine.begin() as connection:
            if "result_status" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE schedule_state ADD COLUMN result_status VARCHAR(20) NOT NULL DEFAULT 'waiting'"
                )
            if "last_error" not in columns:
                connection.exec_driver_sql("ALTER TABLE schedule_state ADD COLUMN last_error TEXT")
            connection.exec_driver_sql(
                "UPDATE schedule_state SET result_status = 'available' "
                "WHERE schedule_hash IS NOT NULL AND result_status = 'waiting'"
            )

    def get(self, schedule_date: str, schedule_time: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(schedule_state).where(
                schedule_state.c.schedule_date == schedule_date,
                schedule_state.c.schedule_time == schedule_time,
            )).mappings().first()
        return dict(row) if row else None

    def list_for_date(self, schedule_date: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(schedule_state).where(
                schedule_state.c.schedule_date == schedule_date,
            )).mappings().all()
        return [dict(row) for row in rows]

    def mark_checked(self, schedule_date: str, schedule_time: str) -> None:
        self.mark_result(schedule_date, schedule_time, "waiting")

    def mark_result(self, schedule_date: str, schedule_time: str, result_status: str, error: str | None = None) -> None:
        now = _now()
        with self.engine.begin() as connection:
            existing = connection.execute(select(schedule_state.c.schedule_date).where(
                schedule_state.c.schedule_date == schedule_date,
                schedule_state.c.schedule_time == schedule_time,
            )).first()
            if existing:
                connection.execute(update(schedule_state).where(
                    schedule_state.c.schedule_date == schedule_date,
                    schedule_state.c.schedule_time == schedule_time,
                ).values(last_checked_at=now, result_status=result_status, last_error=error))
            else:
                connection.execute(schedule_state.insert().values(
                    schedule_date=schedule_date, schedule_time=schedule_time,
                    last_checked_at=now, notification_status="not_sent",
                    result_status=result_status, last_error=error,
                ))

    def save_schedule(self, schedule_date: str, schedule_time: str, content_hash: str, normalized: str, notification_status: str) -> None:
        now = _now()
        with self.engine.begin() as connection:
            previous = connection.execute(select(schedule_state).where(
                schedule_state.c.schedule_date == schedule_date,
                schedule_state.c.schedule_time == schedule_time,
            )).mappings().first()
            values = dict(
                schedule_hash=content_hash, normalized_schedule=normalized,
                first_detected_at=(previous["first_detected_at"] if previous and previous["first_detected_at"] else now),
                last_checked_at=now, notification_status=notification_status,
                result_status="available", last_error=None,
            )
            if previous:
                connection.execute(update(schedule_state).where(
                    schedule_state.c.schedule_date == schedule_date,
                    schedule_state.c.schedule_time == schedule_time,
                ).values(**values))
            else:
                connection.execute(schedule_state.insert().values(
                    schedule_date=schedule_date, schedule_time=schedule_time, **values,
                ))

    def save_notified_schedule(self, schedule_date: str, schedule_time: str, content_hash: str, normalized: str) -> None:
        self.save_schedule(schedule_date, schedule_time, content_hash, normalized, "sent")

    def upsert_subscription(self, endpoint: str, p256dh: str, auth: str) -> bool:
        now = _now()
        with self.engine.begin() as connection:
            existing = connection.execute(select(push_subscriptions.c.endpoint).where(push_subscriptions.c.endpoint == endpoint)).first()
            values = dict(p256dh=p256dh, auth=auth, updated_at=now, active=True)
            if existing:
                connection.execute(update(push_subscriptions).where(push_subscriptions.c.endpoint == endpoint).values(**values))
                return False
            connection.execute(push_subscriptions.insert().values(endpoint=endpoint, created_at=now, **values))
            return True

    def active_subscriptions(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(push_subscriptions).where(push_subscriptions.c.active.is_(True))).mappings().all()
        return [dict(row) for row in rows]

    def active_subscription(self, endpoint: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(push_subscriptions).where(
                push_subscriptions.c.endpoint == endpoint,
                push_subscriptions.c.active.is_(True),
            )).mappings().first()
        return dict(row) if row else None

    def deactivate_subscription(self, endpoint: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(update(push_subscriptions).where(push_subscriptions.c.endpoint == endpoint).values(active=False, updated_at=_now()))

    def close(self) -> None:
        self.engine.dispose()
