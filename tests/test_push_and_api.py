from dataclasses import replace
from types import SimpleNamespace

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
        schedules = client.get("/api/schedules/today")
        assert schedules.status_code == 200 and len(schedules.json()) == 4
        payload = {"endpoint": "https://push.example/one", "keys": {"p256dh": "abc", "auth": "def"}}
        assert client.post("/api/push/subscribe", json=payload).status_code == 201
        assert client.post("/api/push/subscribe", json={"endpoint": "bad", "keys": {}}).status_code == 422
        assert client.request("DELETE", "/api/push/subscribe", json={"endpoint": "https://push.example/one"}).status_code == 200
