from __future__ import annotations

from datetime import date, datetime
import logging
from zoneinfo import ZoneInfo

from .nist_client import NistClient
from .schedule_parser import parse_schedule_result
from .storage import Storage


LOGGER = logging.getLogger(__name__)


class Monitor:
    def __init__(self, client: NistClient, storage: Storage, notifier, schedule_time: str):
        self.client = client
        self.storage = storage
        self.notifier = notifier
        self.schedule_time = schedule_time

    def check(self, today: date | None = None) -> str:
        today = today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
        date_text = today.strftime("%d/%m/%Y")
        try:
            html = self.client.fetch(today, self.schedule_time)
        except Exception as exc:
            LOGGER.warning("NIST ERP request failed for %s %s: %s", date_text, self.schedule_time, exc)
            self.storage.mark_result(date_text, self.schedule_time, "error", f"ERP request failed: {exc}")
            return "request_failed"

        parsed = parse_schedule_result(html)
        if parsed.status == "no_schedule":
            self.storage.mark_result(date_text, self.schedule_time, "no_schedule")
            LOGGER.info("No published schedule found for %s %s", date_text, self.schedule_time)
            return "unavailable"
        if parsed.status == "error" or parsed.schedule is None:
            error = parsed.error or "The ERP schedule response could not be parsed."
            self.storage.mark_result(date_text, self.schedule_time, "error", error)
            LOGGER.warning("NIST ERP parser failed for %s %s: %s", date_text, self.schedule_time, error)
            return "parse_failed"
        schedule = parsed.schedule

        previous = self.storage.get(date_text, self.schedule_time)
        same_schedule = bool(previous and previous["schedule_hash"] == schedule.content_hash)
        if same_schedule and (self.notifier is None or previous["notification_status"] == "sent"):
            self.storage.mark_result(date_text, self.schedule_time, "available")
            LOGGER.info("Schedule is unchanged for %s %s", date_text, self.schedule_time)
            return "unchanged"

        updated = bool(previous and previous["schedule_hash"] and not same_schedule)
        if self.notifier is None:
            self.storage.save_schedule(
                date_text,
                self.schedule_time,
                schedule.content_hash,
                schedule.normalized,
                "not_configured",
            )
            LOGGER.info("Schedule %s detected (Web Push not configured).", "update" if updated else "availability")
            return "detected_without_notification"
        try:
            accepted = self.notifier.send(date_text, self.schedule_time, schedule, updated)
            if accepted == 0:
                raise RuntimeError("The push service did not accept the notification for any subscription.")
        except Exception as exc:
            LOGGER.warning("Web Push notification failed; it will be retried: %s", exc)
            self.storage.mark_result(date_text, self.schedule_time, "error", f"Notification delivery failed: {exc}")
            return "notification_failed"

        self.storage.save_notified_schedule(date_text, self.schedule_time, schedule.content_hash, schedule.normalized)
        LOGGER.info("Schedule notification sent for %s %s", date_text, self.schedule_time)
        return "updated" if updated else "available"
