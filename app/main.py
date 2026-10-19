from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Config, MONITORED_TIMES
from .nist_client import NistClient
from .notifier import WebPushNotifier
from .schedule_monitor import ScheduleMonitor, today_in_kolkata
from .schemas import PushStatusIn, PushSubscriptionIn, PushTestIn, ScheduleOut, UnsubscribeIn
from .storage import Storage


LOGGER = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _notifier(config: Config, storage: Storage) -> WebPushNotifier | None:
    notifier = WebPushNotifier(storage, config.vapid_private_key, config.vapid_claims_email, config.frontend_url)
    return notifier if notifier.configured else None


async def _monitor_loop(monitor: ScheduleMonitor, interval_minutes: int) -> None:
    while True:
        try:
            await monitor.check_all()
        except Exception:
            LOGGER.exception("Unexpected schedule monitor loop failure; it will retry.")
        await asyncio.sleep(interval_minutes * 60)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage = Storage(config.database_url)
        client = NistClient(config.raw_html_dir, config.save_raw_html)
        notifier = _notifier(config, storage)
        monitor = ScheduleMonitor(client, storage, notifier)
        app.state.config = config
        app.state.storage = storage
        app.state.notifier = notifier
        app.state.monitor = monitor
        app.state.monitor_task = asyncio.create_task(_monitor_loop(monitor, config.check_interval_minutes)) if config.start_monitor else None
        yield
        task = app.state.monitor_task
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        storage.close()

    app = FastAPI(title="NIST Bus Alert", version="1.0.0", lifespan=lifespan)
    allowed_origins = [config.frontend_url, "http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys(allowed_origins)),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def public_config(request: Request) -> dict[str, str | bool]:
        config = request.app.state.config
        return {
            "vapidPublicKey": config.vapid_public_key,
            "pushConfigured": bool(config.vapid_public_key and config.vapid_private_key and config.vapid_claims_email),
        }

    @app.get("/api/schedules/today", response_model=list[ScheduleOut])
    def schedules_today(request: Request) -> list[ScheduleOut]:
        day = today_in_kolkata().strftime("%d/%m/%Y")
        states = {row["schedule_time"]: row for row in request.app.state.storage.list_for_date(day)}
        result = []
        for schedule_time in MONITORED_TIMES:
            row = states.get(schedule_time)
            normalized = row.get("normalized_schedule") if row else None
            result_status = row.get("result_status", "waiting") if row else "waiting"
            routes = normalized.splitlines()[1:] if normalized and result_status in {"available", "error"} else []
            updated_at = row.get("last_checked_at") if row else None
            result.append(ScheduleOut(
                time=schedule_time,
                status=result_status,
                routes=routes,
                updated_at=str(updated_at) if updated_at else None,
                error=row.get("last_error") if row else None,
            ))
        return result

    @app.post("/api/push/subscribe", status_code=status.HTTP_201_CREATED)
    def subscribe(payload: PushSubscriptionIn, request: Request) -> dict[str, bool]:
        created = request.app.state.storage.upsert_subscription(str(payload.endpoint), payload.keys.p256dh, payload.keys.auth)
        return {"created": created}

    @app.post("/api/push/status")
    def push_status(payload: PushStatusIn, request: Request) -> dict[str, bool]:
        active = request.app.state.storage.active_subscription(str(payload.endpoint)) is not None
        return {"active": active}

    @app.delete("/api/push/subscribe")
    def unsubscribe(payload: UnsubscribeIn, request: Request) -> dict[str, bool]:
        request.app.state.storage.deactivate_subscription(str(payload.endpoint))
        return {"removed": True}

    @app.post("/api/push/test")
    def test_push(
        payload: PushTestIn,
        request: Request,
        x_push_test_token: str = Header(default=""),
    ) -> dict[str, bool]:
        token = request.app.state.config.push_test_token
        if not token:
            raise HTTPException(status_code=503, detail="Test notifications are disabled on this server.")
        if not hmac.compare_digest(x_push_test_token, token):
            raise HTTPException(status_code=403, detail="Invalid test-notification credential.")
        notifier = request.app.state.notifier
        if notifier is None:
            raise HTTPException(status_code=503, detail="Web Push is not configured on this server.")
        try:
            return notifier.send_test(str(payload.endpoint))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/")
    def frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            FRONTEND_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    return app


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="NIST Bus Alert API and monitor")
    parser.add_argument("--once", action="store_true", help="Check all four NIST schedule times once, then exit.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.once:
        config = Config.from_env()
        storage = Storage(config.database_url)
        try:
            monitor = ScheduleMonitor(NistClient(config.raw_html_dir, config.save_raw_html), storage, _notifier(config, storage))
            print(monitor.check_all_sync())
        finally:
            storage.close()
        return 0
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
