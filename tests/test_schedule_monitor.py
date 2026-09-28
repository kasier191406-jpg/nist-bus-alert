from datetime import datetime, timezone

from app.config import MONITORED_TIMES
from app.schedule_monitor import ScheduleMonitor, today_in_kolkata
from app.storage import Storage


HTML = "<table><tr><th>Route</th><th>Bus Number(s)</th></tr><tr><td>Campus - Town</td><td>12, 18</td></tr></table>"


class Client:
    def fetch(self, schedule_date, schedule_time):
        return HTML


class Notifier:
    def __init__(self): self.calls = []
    def send(self, *args): self.calls.append(args); return 1


def test_kolkata_date_is_used_at_utc_boundary():
    assert today_in_kolkata(datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)).isoformat() == "2026-09-29"
    assert today_in_kolkata(datetime(2026, 9, 28, 17, 0, tzinfo=timezone.utc)).isoformat() == "2026-09-28"


def test_all_four_times_are_checked_and_independent(tmp_path):
    storage = Storage(tmp_path / "state.db")
    notifier = Notifier()
    results = ScheduleMonitor(Client(), storage, notifier).check_all_sync(today_in_kolkata(datetime(2026, 9, 28, 20, tzinfo=timezone.utc)))
    assert set(results) == set(MONITORED_TIMES)
    assert len(notifier.calls) == 4
    assert len(storage.list_for_date("29/09/2026")) == 4
    storage.close()
