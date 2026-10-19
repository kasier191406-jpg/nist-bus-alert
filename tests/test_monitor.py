from datetime import date

from app.monitor import Monitor
from app.storage import Storage


PUBLISHED_HTML = """
<table><tr><th>Bus No</th><th>Route</th></tr>
<tr><td>12</td><td>City Center - NIST</td></tr></table>
"""
CHANGED_HTML = """
<table><tr><th>Bus No</th><th>Route</th></tr>
<tr><td>15</td><td>Airport - NIST</td></tr></table>
"""


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def fetch(self, schedule_date, schedule_time):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def send(self, schedule_date, schedule_time, schedule, updated):
        self.calls.append((schedule_date, schedule_time, schedule, updated))


def make_monitor(tmp_path, responses):
    notifier = FakeNotifier()
    storage = Storage(tmp_path / "state.db")
    return Monitor(FakeClient(responses), storage, notifier, "03:20 PM"), notifier, storage


def test_same_schedule_twice_sends_only_one_notification(tmp_path):
    monitor, notifier, storage = make_monitor(tmp_path, [PUBLISHED_HTML, PUBLISHED_HTML])
    assert monitor.check(date(2026, 9, 28)) == "available"
    assert monitor.check(date(2026, 9, 28)) == "unchanged"
    assert len(notifier.calls) == 1
    storage.close()


def test_changed_schedule_sends_an_update(tmp_path):
    monitor, notifier, storage = make_monitor(tmp_path, [PUBLISHED_HTML, CHANGED_HTML])
    monitor.check(date(2026, 9, 28))
    assert monitor.check(date(2026, 9, 28)) == "updated"
    assert len(notifier.calls) == 2
    assert notifier.calls[-1][-1] is True
    storage.close()


def test_server_error_is_logged_and_retried_without_crashing(tmp_path):
    monitor, notifier, storage = make_monitor(tmp_path, [OSError("temporary outage"), PUBLISHED_HTML])
    assert monitor.check(date(2026, 9, 28)) == "request_failed"
    state = storage.get("28/09/2026", "03:20 PM")
    assert state["result_status"] == "error"
    assert "temporary outage" in state["last_error"]
    assert monitor.check(date(2026, 9, 28)) == "available"
    assert len(notifier.calls) == 1
    storage.close()


def test_a_new_date_has_fresh_schedule_detection(tmp_path):
    monitor, notifier, storage = make_monitor(tmp_path, [PUBLISHED_HTML, PUBLISHED_HTML])
    assert monitor.check(date(2026, 9, 28)) == "available"
    assert monitor.check(date(2026, 9, 29)) == "available"
    assert len(notifier.calls) == 2
    storage.close()


def test_schedule_is_stored_and_suppressed_when_telegram_is_not_configured(tmp_path):
    storage = Storage(tmp_path / "state.db")
    monitor = Monitor(FakeClient([PUBLISHED_HTML, PUBLISHED_HTML]), storage, None, "03:20 PM")
    assert monitor.check(date(2026, 9, 28)) == "detected_without_notification"
    assert monitor.check(date(2026, 9, 28)) == "unchanged"
    state = storage.get("28/09/2026", "03:20 PM")
    assert state["schedule_hash"]
    assert state["first_detected_at"]
    assert state["notification_status"] == "not_configured"
    storage.close()


def test_confirmed_no_schedule_and_parser_failure_are_reported_separately(tmp_path):
    no_schedule_html = "<html><body>No Schedule Found for the selected date and time</body></html>"
    malformed_html = "<html><body>Service temporarily unavailable</body></html>"
    monitor, _, storage = make_monitor(tmp_path, [no_schedule_html, malformed_html])
    assert monitor.check(date(2026, 9, 28)) == "unavailable"
    state = storage.get("28/09/2026", "03:20 PM")
    assert state["result_status"] == "no_schedule"
    assert state["schedule_hash"] is None
    assert monitor.check(date(2026, 9, 28)) == "parse_failed"
    state = storage.get("28/09/2026", "03:20 PM")
    assert state["result_status"] == "error"
    assert "recognized schedule" in state["last_error"]
    storage.close()


def test_fetch_failure_preserves_last_known_good_schedule(tmp_path):
    monitor, notifier, storage = make_monitor(tmp_path, [PUBLISHED_HTML, OSError("network timeout")])
    assert monitor.check(date(2026, 9, 28)) == "available"
    previous = storage.get("28/09/2026", "03:20 PM")
    assert monitor.check(date(2026, 9, 28)) == "request_failed"
    current = storage.get("28/09/2026", "03:20 PM")
    assert current["schedule_hash"] == previous["schedule_hash"]
    assert current["normalized_schedule"] == previous["normalized_schedule"]
    assert current["result_status"] == "error"
    assert len(notifier.calls) == 1
    storage.close()
