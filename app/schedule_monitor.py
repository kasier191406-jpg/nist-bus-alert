from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import MONITORED_TIMES
from .monitor import Monitor


LOGGER = logging.getLogger(__name__)


def today_in_kolkata(now: datetime | None = None) -> date:
    if now is None:
        return datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if now.tzinfo is None:
        raise ValueError("A timezone-aware datetime is required.")
    return now.astimezone(ZoneInfo("Asia/Kolkata")).date()


class ScheduleMonitor:
    def __init__(self, client, storage, notifier):
        self.client = client
        self.storage = storage
        self.notifier = notifier

    def check_all_sync(self, today: date | None = None) -> dict[str, str]:
        schedule_date = today or today_in_kolkata()
        results: dict[str, str] = {}
        for schedule_time in MONITORED_TIMES:
            try:
                LOGGER.info("Checking NIST schedule: %s", schedule_time)
                results[schedule_time] = Monitor(self.client, self.storage, self.notifier, schedule_time).check(schedule_date)
            except Exception as exc:
                LOGGER.exception("Unexpected monitor failure for %s: %s", schedule_time, exc)
                results[schedule_time] = "failed"
        return results

    async def check_all(self) -> dict[str, str]:
        return await asyncio.to_thread(self.check_all_sync)
