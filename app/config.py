from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine.url import make_url


MONITORED_TIMES = ("06:15 AM", "08:15 AM", "09:50 AM", "03:20 PM")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    database_url: str
    raw_html_dir: Path
    save_raw_html: bool
    check_interval_minutes: int
    timezone: str
    frontend_url: str
    vapid_private_key: str
    vapid_public_key: str
    vapid_claims_email: str
    start_monitor: bool
    push_test_token: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        render_runtime = _bool("RENDER", False) or bool(os.getenv("RENDER_SERVICE_ID"))
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            if render_runtime:
                raise ValueError("Render requires DATABASE_URL to be configured for durable storage.")
            database_url = "sqlite:///data/nist_bus_alert.db"
        if render_runtime and database_url.lower().startswith("sqlite:"):
            disk_path = os.getenv("PERSISTENT_DISK_PATH", "").strip()
            sqlite_path = make_url(database_url).database
            if not disk_path or not sqlite_path or sqlite_path == ":memory:":
                raise ValueError(
                    "Render SQLite storage requires an attached persistent disk and PERSISTENT_DISK_PATH; "
                    "otherwise subscriptions and schedule state are lost on restarts or deployments."
                )
            try:
                Path(sqlite_path).resolve().relative_to(Path(disk_path).resolve())
            except ValueError as exc:
                raise ValueError("The SQLite DATABASE_URL must be located under PERSISTENT_DISK_PATH on Render.") from exc
        interval = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
        if interval < 1:
            raise ValueError("CHECK_INTERVAL_MINUTES must be at least 1.")
        timezone = os.getenv("TIMEZONE", "Asia/Kolkata").strip()
        if timezone != "Asia/Kolkata":
            raise ValueError("TIMEZONE must be Asia/Kolkata for NIST schedules.")
        return cls(
            database_url=database_url,
            raw_html_dir=Path(os.getenv("RAW_HTML_DIR", "data/raw_html")),
            save_raw_html=_bool("SAVE_RAW_HTML", True),
            check_interval_minutes=interval,
            timezone=timezone,
            frontend_url=os.getenv("FRONTEND_URL", "http://localhost:8000").rstrip("/"),
            vapid_private_key=os.getenv("VAPID_PRIVATE_KEY", "").strip(),
            vapid_public_key=os.getenv("VAPID_PUBLIC_KEY", "").strip(),
            vapid_claims_email=os.getenv("VAPID_CLAIMS_EMAIL", "").strip(),
            start_monitor=_bool("START_MONITOR", True),
            push_test_token=os.getenv("PUSH_TEST_TOKEN", "").strip(),
        )
