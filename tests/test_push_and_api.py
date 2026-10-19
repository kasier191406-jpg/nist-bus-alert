from dataclasses import replace
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app
from app.notifier import WebPushNotifier
from app.schedule_parser import parse_schedule
from app.storage import Storage


def test_subscriptions_support_duplicates_and_multiple_devices(tmp_path):
    storage = Storage(tmp_path / "state.db")
    assert storage.upsert_subscription("https://push.example/one", "key1", "auth1") is True
    assert storage.upsert_subscription("https://push.example/one", "key2", "auth2") is False
    assert storage.upsert_subscription("https://push.example/two", "key3", "auth3") is True
    assert len(storage.active_subscriptions()) == 2
    storage.deactivate_subscription("https://push.example/one")
    assert len(storage.active_subscriptions()) == 1
    storage.close()


def test_web_push_notifies_every_active_subscription(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "state.db")
    storage.upsert_subscription("https://push.example/one", "key1", "auth1")
    storage.upsert_subscription("https://push.example/two", "key2", "auth2")
    calls = []
    monkeypatch.setattr("app.notifier.webpush", lambda **kwargs: calls.append(kwargs))
    schedule = parse_schedule("<table><tr><th>Route</th><th>Bus Number(s)</th></tr><tr><td>Campus - Town</td><td>12</td></tr></table>")
    assert WebPushNotifier(storage, "private", "test@example.com", "http://localhost:8000").send("28/09/2026", "08:15 AM", schedule, False) == 2
    assert len(calls) == 2
    storage.close()


def test_invalid_web_push_subscription_is_deactivated(monkeypatch, tmp_path):
    from pywebpush import WebPushException
    storage = Storage(tmp_path / "state.db")
    endpoint = "https://push.example/gone"
    storage.upsert_subscription(endpoint, "key", "auth")
    monkeypatch.setattr("app.notifier.webpush", lambda **kwargs: (_ for _ in ()).throw(WebPushException("gone", SimpleNamespace(status_code=410))))
    schedule = parse_schedule("<table><tr><th>Route</th><th>Bus Number(s)</th></tr><tr><td>Campus - Town</td><td>12</td></tr></table>")
    assert WebPushNotifier(storage, "private", "test@example.com", "http://localhost:8000").send("28/09/2026", "08:15 AM", schedule, False) == 0
    assert storage.active_subscriptions() == []
    storage.close()


def test_api_health_schedule_and_subscription_endpoints(tmp_path):
    config = replace(Config.from_env(), database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}", start_monitor=False)
    with TestClient(create_app(config)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/sw.js").headers["service-worker-allowed"] == "/"
        assert client.get("/api/config").json() == {"vapidPublicKey": "", "pushConfigured": False}
        schedules = client.get("/api/schedules/today")
        assert schedules.status_code == 200 and len(schedules.json()) == 4
        payload = {"endpoint": "https://push.example/one", "keys": {"p256dh": "abc", "auth": "def"}}
        assert client.post("/api/push/subscribe", json=payload).status_code == 201
        assert client.post("/api/push/status", json={"endpoint": payload["endpoint"]}).json() == {"active": True}
        assert client.post("/api/push/status", json={"endpoint": "https://push.example/missing"}).json() == {"active": False}
        assert client.post("/api/push/subscribe", json={"endpoint": "bad", "keys": {}}).status_code == 422
        assert client.request("DELETE", "/api/push/subscribe", json={"endpoint": "https://push.example/one"}).status_code == 200
        assert client.post("/api/push/status", json={"endpoint": payload["endpoint"]}).json() == {"active": False}


def test_test_notification_is_authenticated_and_targets_one_subscription(monkeypatch, tmp_path):
    config = replace(
        Config.from_env(),
        database_url=f"sqlite:///{(tmp_path / 'test-push.db').as_posix()}",
        start_monitor=False,
        push_test_token="long-test-secret",
        vapid_private_key="private",
        vapid_claims_email="test@example.com",
    )
    calls = []
    monkeypatch.setattr("app.notifier.webpush", lambda **kwargs: calls.append(kwargs))
    with TestClient(create_app(config)) as client:
        first = {"endpoint": "https://push.example/one", "keys": {"p256dh": "key1", "auth": "auth1"}}
        second = {"endpoint": "https://push.example/two", "keys": {"p256dh": "key2", "auth": "auth2"}}
        client.post("/api/push/subscribe", json=first)
        client.post("/api/push/subscribe", json=second)
        url = "/api/push/test"
        assert client.post(url, json={"endpoint": first["endpoint"]}).status_code == 403
        response = client.post(
            url,
            json={"endpoint": first["endpoint"]},
            headers={"X-Push-Test-Token": "long-test-secret"},
        )
        assert response.status_code == 200
        assert response.json() == {"provider_accepted": True, "device_display_confirmed": False}
        assert len(calls) == 1
        assert calls[0]["subscription_info"]["endpoint"] == first["endpoint"]
        assert '"TEST: NIST Bus Alert"' in calls[0]["data"]
        assert all(item["status"] == "waiting" for item in client.get("/api/schedules/today").json())


def test_push_subscription_rejects_http_endpoint(tmp_path):
    config = replace(Config.from_env(), database_url=f"sqlite:///{(tmp_path / 'invalid.db').as_posix()}", start_monitor=False)
    with TestClient(create_app(config)) as client:
        response = client.post(
            "/api/push/subscribe",
            json={"endpoint": "http://push.example/one", "keys": {"p256dh": "abc", "auth": "def"}},
        )
        assert response.status_code == 422


def test_sqlite_url_creates_parent_directory(tmp_path):
    database = tmp_path / "missing" / "nested" / "state.db"
    storage = Storage(f"sqlite:///{database.as_posix()}")
    assert database.exists()
    storage.close()


def test_legacy_sqlite_state_is_migrated_without_losing_schedule(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schedule_state (
            schedule_date VARCHAR(10) NOT NULL,
            schedule_time VARCHAR(8) NOT NULL,
            schedule_hash VARCHAR(64),
            normalized_schedule TEXT,
            first_detected_at VARCHAR(40),
            last_checked_at VARCHAR(40) NOT NULL,
            notification_status VARCHAR(32) NOT NULL,
            PRIMARY KEY (schedule_date, schedule_time)
        );
        INSERT INTO schedule_state VALUES (
            '28/09/2026', '08:15 AM', 'hash', 'route | bus', 'first', 'last', 'sent'
        );
        """
    )
    connection.close()

    storage = Storage(database)
    state = storage.get("28/09/2026", "08:15 AM")
    assert state["schedule_hash"] == "hash"
    assert state["result_status"] == "available"
    assert state["last_error"] is None
    storage.close()


def test_render_runtime_accepts_configured_sqlite_without_persistent_disk(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/nist_bus_alert.db")
    monkeypatch.delenv("PERSISTENT_DISK_PATH", raising=False)
    assert Config.from_env().database_url == "sqlite:////tmp/nist_bus_alert.db"

def test_render_runtime_rejects_missing_database_url(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Config.from_env()


def test_schedule_api_reports_no_schedule_and_error_states(tmp_path):
    config = replace(Config.from_env(), database_url=f"sqlite:///{(tmp_path / 'states.db').as_posix()}", start_monitor=False)
    app = create_app(config)
    with TestClient(app) as client:
        app.state.storage.mark_result("19/10/2026", "06:15 AM", "no_schedule")
        app.state.storage.mark_result("19/10/2026", "08:15 AM", "error", "ERP timeout")
        schedules = {item["time"]: item for item in client.get("/api/schedules/today").json()}
        assert schedules["06:15 AM"]["status"] == "no_schedule"
        assert schedules["08:15 AM"]["status"] == "error"
        assert schedules["08:15 AM"]["error"] == "ERP timeout"
