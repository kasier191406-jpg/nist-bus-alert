from __future__ import annotations

import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush

from .schedule_parser import Schedule
from .storage import Storage


LOGGER = logging.getLogger(__name__)


class WebPushNotifier:
    def __init__(self, storage: Storage, private_key: str, claims_email: str, frontend_url: str):
        self.storage = storage
        self.private_key = private_key
        self.claims_email = claims_email
        self.frontend_url = frontend_url

    @property
    def configured(self) -> bool:
        return bool(self.private_key and self.claims_email)

    def send(self, schedule_date: str, schedule_time: str, schedule: Schedule, updated: bool) -> int:
        if not self.configured:
            LOGGER.info("Web Push is not configured; schedule state will be retained without a notification.")
            return 0
        title = f"NIST Bus Schedule {'Updated' if updated else 'Available'} - {schedule_time.lstrip('0')}"
        routes = "\n".join(schedule.display_lines[1:3])
        payload = json.dumps({
            "title": title,
            "body": ("Today's schedule has changed. " if updated else "Today's bus schedule is available. ") + routes[:220],
            "url": self.frontend_url,
            "tag": f"nist-{schedule_date}-{schedule_time}",
        })
        sent = 0
        failed = 0
        for subscription in self.storage.active_subscriptions():
            subscription_info: dict[str, Any] = {
                "endpoint": subscription["endpoint"],
                "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=self.private_key,
                    vapid_claims={"sub": f"mailto:{self.claims_email}"},
                )
                sent += 1
            except WebPushException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in {404, 410}:
                    self.storage.deactivate_subscription(subscription["endpoint"])
                    LOGGER.info("Deactivated invalid Web Push subscription.")
                else:
                    failed += 1
                    LOGGER.warning("Web Push delivery failed: %s", exc)
            except Exception as exc:
                failed += 1
                LOGGER.warning("Web Push delivery failed: %s", exc)
        LOGGER.info("Sent notification to %s subscription(s).", sent)
        if failed and not sent:
            raise RuntimeError("No active Web Push subscription accepted the notification.")
        return sent
