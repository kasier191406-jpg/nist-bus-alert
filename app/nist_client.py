from __future__ import annotations

from datetime import date
from pathlib import Path
import logging

import requests


LOGGER = logging.getLogger(__name__)
ENDPOINT = "https://nis.nist.edu/ois/FuelandTransportationManagement/forms/rptPrintScheduleWithoutLogin.php"


class NistClient:
    def __init__(self, raw_html_dir: Path, save_raw_html: bool = True, timeout_seconds: int = 20):
        self.raw_html_dir = raw_html_dir
        self.save_raw_html = save_raw_html
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "NIST-Bus-Alert/1.0 (personal schedule monitor)"})

    def fetch(self, schedule_date: date, schedule_time: str) -> str:
        response = self.session.get(
            ENDPOINT,
            params={"sesTime": schedule_time, "sesDate": schedule_date.strftime("%d/%m/%Y")},
            timeout=self.timeout_seconds,
        )
        html = response.text
        relevant_headers = {
            name: response.headers[name]
            for name in ("Content-Type", "Server", "Location", "X-Request-ID")
            if name in response.headers
        }
        LOGGER.info(
            "NIST ERP response: method=GET url=%s status=%s headers=%s",
            response.url,
            response.status_code,
            relevant_headers,
        )
        if self.save_raw_html:
            self._save_raw_html(schedule_date, schedule_time, html)
        # NIST serves its normal ERP "No Schedule Found" page with HTTP 500.
        # It is a valid empty result; unrelated error responses remain retryable failures.
        if response.status_code == 500 and "No Schedule Found for the selected date and time" in html:
            LOGGER.info("NIST returned its valid no-schedule page for %s", schedule_time)
            return html
        response.raise_for_status()
        return html

    def _save_raw_html(self, schedule_date: date, schedule_time: str, html: str) -> Path:
        self.raw_html_dir.mkdir(parents=True, exist_ok=True)
        time_part = schedule_time.replace(":", "-").replace(" ", "_")
        path = self.raw_html_dir / f"{schedule_date:%Y-%m-%d}_{time_part}.html"
        path.write_text(html, encoding="utf-8")
        LOGGER.info("Saved raw ERP response to %s", path)
        return path
