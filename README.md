# NIST Bus Alert

NIST Bus Alert is a small Android-first PWA and FastAPI service. It checks the public NIST ERP schedule for today's date in `Asia/Kolkata`, detects a new or changed schedule, and sends Web Push notifications to subscribed browsers.

The four fixed daily checks are `06:15 AM`, `08:15 AM`, `09:50 AM`, and `03:20 PM`. There are no accounts, passwords, stop preferences, or date selection.

## Architecture

Android Chrome PWA -> Vercel static frontend -> Render FastAPI service -> PostgreSQL -> NIST ERP.

For local development, FastAPI serves the PWA and uses SQLite. The same repository code accepts a PostgreSQL `DATABASE_URL` in production. One FastAPI process runs the API and the five-minute polling task. The polling task is intentionally simple for this small MVP; production should run one service instance to avoid two instances sending duplicate notifications.

NIST sometimes returns a rendered `No Schedule Found for the selected date and time` page with HTTP 500. The client recognizes that exact ERP page as a valid empty result. Other errors are logged and retried at the next interval.

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

- No table: no notification.
- First published hash: save and notify active subscriptions.
- Same hash: no repeat notification.
- Changed hash: save and send an update.
- A new India date or a different fixed time has its own independent state.

## Deployment

### Render

[`render.yaml`](render.yaml) declares a FastAPI web service and PostgreSQL database. Add these secret variables in the Render dashboard: `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_CLAIMS_EMAIL`, and `FRONTEND_URL`. Set `DATABASE_URL` from the Render database connection string, preferably as `postgresql+psycopg://...` for SQLAlchemy/psycopg 3. Keep exactly one monitoring service instance.

### Vercel

Deploy the `frontend/` directory as a static Vercel project. Before deploying, set `window.NIST_BUS_API_BASE` in [`frontend/config.js`](frontend/config.js) to your HTTPS Render API origin, for example `https://nist-bus-alert.onrender.com`. Set Render’s `FRONTEND_URL` to the matching Vercel origin; FastAPI then allows that origin via CORS. The API allows only that origin and common localhost development origins, not wildcard CORS.

The bundled `frontend/manifest.webmanifest`, `sw.js`, and icon make the app installable where the browser supports PWAs.

## API

- `GET /health` - health check
- `GET /api/schedules/today` - four fixed times and current known states
- `GET /api/config` - public VAPID key only
- `POST /api/push/subscribe` - register/update a browser subscription
- `DELETE /api/push/subscribe` - deactivate a subscription

## Limitations

The app cannot create VAPID keys or deploy Render/Vercel without your accounts. Web Push needs HTTPS and valid VAPID values. Render’s periodic polling should use a single running instance; horizontal scaling requires a database-level lock, which is deliberately outside this four-user MVP.
