# NIST Bus Alert

NIST Bus Alert is a small Android-first PWA and FastAPI service. It checks the public NIST ERP schedule for today's date in `Asia/Kolkata`, detects a new or changed schedule, and sends Web Push notifications to subscribed browsers.

The four fixed daily checks are `06:15 AM`, `08:15 AM`, `09:50 AM`, and `03:20 PM`. There are no accounts, passwords, stop preferences, or date selection.

## Architecture

Android Chrome PWA -> Vercel static frontend (or Render-hosted frontend) -> Render FastAPI service -> PostgreSQL -> NIST ERP.

For local development, FastAPI serves the PWA and uses SQLite, creating its parent directory when needed. Render can also start with SQLite configured in `DATABASE_URL`, but its ordinary filesystem is ephemeral: subscriptions and schedule state stored there can be lost on restarts or deployments. One FastAPI process runs the API and the five-minute polling task; run one service instance to avoid duplicate polling and notifications.

NIST sometimes returns a rendered `No Schedule Found for the selected date and time` page with HTTP 500. The client accepts that exact ERP page as an empty result, but other HTTP errors and unrecognized HTML are reported separately and retried at the next interval. The API exposes `waiting`, `available`, `no_schedule`, and `error` per schedule time.

## Local setup

This project is tested on Python 3.14.4.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set the public VAPID key and private values in `.env`. The default SQLite configuration needs no database setup.

```env
DATABASE_URL=sqlite:///data/nist_bus_alert.db
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
VAPID_CLAIMS_EMAIL=you@example.com
PUSH_TEST_TOKEN=
FRONTEND_URL=http://localhost:8000
TIMEZONE=Asia/Kolkata
CHECK_INTERVAL_MINUTES=5
START_MONITOR=true
```

`VAPID_PRIVATE_KEY`, database URLs, and other secrets must never be committed. `.env` and the local `data/` directory are ignored by Git.

## VAPID keys

Generate a local PEM key, then print its browser-facing application-server key:

```powershell
.\.venv\Scripts\vapid.exe --gen
.\.venv\Scripts\vapid.exe --applicationServerKey --private-key private_key.pem
```

Put the second command's output in `VAPID_PUBLIC_KEY`. Locally, set `VAPID_PRIVATE_KEY=private_key.pem`; `pywebpush` accepts a key path. For Render, store the PEM contents as the `VAPID_PRIVATE_KEY` secret instead of relying on the service filesystem. Keep the private key only in environment variables or an ignored local file.

## Run and test

Run tests without NIST access or notification secrets:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run a safe one-shot ERP check for all four times:

```powershell
.\.venv\Scripts\python.exe -m app.main --once
```

Start the API, PWA, and monitor together:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` on Android or desktop. Use HTTPS in production before testing Web Push; Android Chrome requires a secure context outside localhost.

## Android notification setup

1. Deploy the frontend over HTTPS and open it in Android Chrome.
2. Install/add the site to the home screen if desired.
3. Press **Enable Notifications** and grant permission.
4. The browser registers a service worker and posts its anonymous subscription to the API.
5. Closing the PWA does not remove the subscription. A new or changed NIST schedule sends a push notification that opens the app.

Each browser/device has its own subscription. Invalid `404`/`410` subscriptions are marked inactive during delivery. The API never exposes subscription keys or VAPID secrets.

## Duplicate detection

The parser strips incidental whitespace, takes the schedule table’s meaningful cells, creates a normalized representation, and hashes it with SHA-256. State is keyed by `date + schedule time`.

- Confirmed no-schedule page: no notification.
- Unexpected HTTP responses or unrecognized HTML: record an error and retry without replacing the last known schedule.
- First published hash: save and notify active subscriptions.
- Same hash: no repeat notification.
- Changed hash: save and send an update.
- A new India date or a different fixed time has its own independent state.

## Deployment

### Render

[`render.yaml`](render.yaml) declares a FastAPI web service and a PostgreSQL database. If the deployed service is currently configured with SQLite, the app will start with that `DATABASE_URL`; SQLite data on Render's ordinary ephemeral filesystem does not survive restarts or deployments, so subscriptions and schedule state may be lost. The Render manifest's PostgreSQL resource is not required for startup when a configured SQLite URL is used. Keep exactly one monitoring service instance.

### Vercel

Deploy the repository root as a static Vercel project so [`vercel.json`](vercel.json) can map `/static/*` and `/sw.js` to the actual files under `frontend/`. [`frontend/config.js`](frontend/config.js) points non-local deployments at the provided Render service URL; update it if the API origin changes. Set Render’s `FRONTEND_URL` to the exact Vercel origin so FastAPI allows that origin via CORS. The API allows only that origin and common localhost development origins, not wildcard CORS.

The root-scoped service worker is served at `/sw.js` with `Service-Worker-Allowed: /`. The bundled manifest and icon make the app installable where the browser supports PWAs.

## API

- `GET /health` - health check
- `GET /api/schedules/today` - four fixed times and current known states
- `GET /api/config` - public VAPID key and a non-secret readiness flag
- `POST /api/push/subscribe` - register/update a browser subscription
- `POST /api/push/status` - check whether a device subscription is active
- `DELETE /api/push/subscribe` - deactivate a subscription
- `POST /api/push/test` - send a labelled test to one active subscription; requires `PUSH_TEST_TOKEN` in `X-Push-Test-Token`

### Test notification

Set a strong, private `PUSH_TEST_TOKEN` in Render. Do not put it in frontend JavaScript. On the subscribed Android device, retrieve that device’s endpoint from its browser’s Web Push subscription and send only that endpoint to the protected test route. A successful response means the push provider accepted the message; it cannot confirm that Android displayed it.

The test payload is labelled `TEST`, targets exactly one active endpoint, and does not read or update schedule state. Never use the test endpoint without the secret header.

```powershell
$headers = @{ "X-Push-Test-Token" = $env:PUSH_TEST_TOKEN }
$body = @{ endpoint = $env:PUSH_SUBSCRIPTION_ENDPOINT } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://nist-bus-alert-2.onrender.com/api/push/test" -Headers $headers -ContentType "application/json" -Body $body
```

## Limitations

The app cannot create VAPID keys or deploy Render/Vercel without your accounts. Render requires `DATABASE_URL`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_CLAIMS_EMAIL`, `FRONTEND_URL`, and (to enable protected test sends) `PUSH_TEST_TOKEN`. Web Push needs HTTPS and a matching VAPID key pair. Render’s periodic polling should use a single running instance; horizontal scaling requires a database-level lock, which is deliberately outside this four-user MVP. Free web-service spin-down can delay polling and notification delivery until the service wakes; local tests do not verify deployed push delivery.
