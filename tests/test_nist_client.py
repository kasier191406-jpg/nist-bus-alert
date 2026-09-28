from datetime import date
from pathlib import Path

import pytest
import requests

from app.nist_client import NistClient


NO_SCHEDULE = "<p>No Schedule Found for the selected date and time.</p>"


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.url = "https://nis.nist.edu/test"
        self.headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.headers = {}

    def get(self, url, **kwargs):
        if self.error:
            raise self.error
        return self.response


def test_http_200_schedule_is_returned(tmp_path):
    client = NistClient(tmp_path)
    client.session = FakeSession(FakeResponse(200, "<table>published</table>"))
    assert client.fetch(date(2026, 9, 28), "08:15 AM") == "<table>published</table>"


def test_nist_500_no_schedule_page_is_a_valid_empty_result(tmp_path):
    client = NistClient(tmp_path)
    client.session = FakeSession(FakeResponse(500, NO_SCHEDULE))
    assert client.fetch(date(2026, 9, 28), "03:20 PM") == NO_SCHEDULE
    assert (tmp_path / "2026-09-28_03-20_PM.html").exists()


def test_unexpected_http_error_and_connection_error_raise_for_retry(tmp_path):
    client = NistClient(tmp_path)
    client.session = FakeSession(FakeResponse(500, "<html>database failure</html>"))
    with pytest.raises(requests.HTTPError):
        client.fetch(date(2026, 9, 28), "03:20 PM")
    client.session = FakeSession(error=requests.Timeout("slow"))
    with pytest.raises(requests.Timeout):
        client.fetch(date(2026, 9, 28), "03:20 PM")
