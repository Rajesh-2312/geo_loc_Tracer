# Location Tracer (consent-based)

A small Flask app for **consent-based live location sharing** over a web link.

You create a labeled tracking link and send it to someone. When they open it,
their browser shows its native location-permission prompt — location is shared
**only if they tap Allow**. You watch incoming positions on a private,
live-updating map.

> **Important — read this first.** This tool cannot and does not locate a phone
> from its IMEI, and it cannot track anyone silently. The browser always asks
> the recipient for permission, and they can stop at any time. Only share links
> with people who have agreed. Tracking a person's location without their
> consent is illegal in most countries and is not what this project is for.

## What it is *not*

- Not an IMEI locator. Mapping an IMEI to a location is only possible inside a
  mobile carrier's core network or for law enforcement with a warrant. No app
  can do it, and any site claiming to is a scam or malware.
- Not covert tracking / stalkerware. Every location fix requires the recipient's
  live, in-browser permission.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt` (only dependency is Flask)

## Run

```bash
pip install -r requirements.txt
python app.py
```

The server starts on `http://localhost:5000`. By default it uses a local
SQLite database (`tracer.db`) created automatically on first run. To store data
in Supabase instead, see the next section.

## Storage: local SQLite (default) or Supabase

The app has two interchangeable storage backends (see `store.py`):

- **SQLite** (default) — zero setup, a local file. Great for development.
- **Supabase Postgres** — cloud storage, used automatically when
  `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are set.

Only the Flask backend talks to Supabase, using the **service_role** key. The
browser never contacts Supabase, so the anon key is not needed here and the
service key stays server-side.

### Enable Supabase

1. **Create the tables.** In your Supabase project open **SQL Editor → New
   query**, paste the contents of [`supabase_schema.sql`](supabase_schema.sql),
   and run it. (This is the one step that must be done in Supabase — the app
   cannot create tables for you.)
2. **Add credentials.** Copy `.env.example` to `.env` and fill in:
   ```
   SUPABASE_URL=https://<your-project-ref>.supabase.co
   SUPABASE_SERVICE_KEY=<your service_role secret>
   ```
   `.env` is gitignored. Find both values in **Project Settings → API**.
3. Restart the app. On startup it now uses Supabase; new sessions and location
   pings are written to your Postgres tables.

> **Security:** the `service_role` key bypasses Row-Level Security — never put
> it in front-end code, never commit it, and rotate it if it is ever exposed
> (Project Settings → API → reset). The schema enables RLS with no public
> policies, so the anon/public role cannot read these tables directly.

To switch back to SQLite, remove or blank out those two values in `.env`.

## How to use

1. Open `http://localhost:5000/`.
2. Enter a label — who is asking and why (shown to recipients) — choose how
   long the link stays valid (1 hour to 7 days), and how many people can join
   (1–10, default 5).
3. You get two links plus a QR code:
   - **Share link** — send this to the other person. A **QR code** is shown so
     they can scan it with a phone camera instead of copying the URL.
   - **Dashboard link** — keep this private; it contains your secret owner key
     and shows the live location. Anyone with only the share link cannot see
     any location.
4. Open the dashboard link yourself. Have the other person open the share link
   and tap **Share my location** → **Allow** in their browser.
5. Their position appears on your map and updates live. They can tap **Stop
   sharing** any time.

## Group tracking: multiple people per link

One link can be shared with several people (a "group"). At creation you choose
**how many people can join** (1–10, default 5). Each device that opens the link
and taps *Share my location*:

1. Enters a name (shown on the map) and **joins** the link as a *member*. Once
   the member cap is reached, further joins are refused ("This link is full").
2. Streams its own location, tagged to that member.

The dashboard then shows **one colored marker + trail per person**, a live
legend listing everyone with their last-seen time (live/idle), and a
`joined / max` counter. Each member has a private member token (kept in their
browser), so a refresh keeps their identity and does not use up another slot.

A member tapping *Stop sharing* only stops their own stream — it does not end
tracking for the rest of the group. The link owner can still end the whole
session for everyone via the stop endpoint.

## Session expiry

Every link has an expiry time chosen at creation (default 24 hours). After it
passes, the share page shows an "expired" notice, new location pings are
rejected, and the dashboard shows **Link expired**. This bounds how long a link
can ever be used, even if you forget to stop it.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite in `tests/` covers session creation, owner-key authorization, the
member join cap, per-member tracking, ping ingestion and retrieval, coordinate
validation, the stop flow, session expiry, and QR generation.

## Deploying on GitHub Pages (static build)

GitHub Pages serves **static files only** — it cannot run the Flask backend. So
the `docs/` folder contains a **serverless version** of the app: the browser
talks to Supabase directly using the **public anon key**, and all the backend
logic lives in Postgres functions (`supabase_functions.sql`). No Python server
is involved.

```
docs/
  index.html      create a link
  share.html      ?t=<share_token>            join + share location
  dashboard.html  ?t=<share_token>&key=<owner_key>   live map
  js/config.js    Supabase URL + anon key + rpc() helper
```

### Security model (important)

- The **anon** key is public and safe to ship in the browser. The
  **service_role** key is never used by this build.
- `supabase_functions.sql` **revokes** all direct table access from the anon
  role and exposes only a few `SECURITY DEFINER` functions
  (`create_session`, `session_info`, `join_session`, `ping`, `get_locations`).
  Those functions check the `share_token` / `owner_key` / `member_token`
  themselves, so the anon key can't read anyone's location without the right
  token.

### Setup

1. In Supabase, run **`supabase_schema.sql`** then **`supabase_functions.sql`**
   in the SQL Editor.
2. Confirm `docs/js/config.js` has your project URL and **anon** key.
3. On GitHub: **Settings → Pages → Source: Deploy from a branch → `main` /
   `docs`**. (If you added a Jekyll workflow earlier, delete it — this build is
   plain static files, and `docs/.nojekyll` tells Pages not to run Jekyll.)
4. Open `https://<user>.github.io/geo_loc_Tracer/`. Pages is HTTPS, so the
   browser geolocation prompt works.

> The Flask app at the repo root is unchanged and still works for local use or
> Render hosting; the two builds share the same Supabase tables.

## Deployment (Render + GitHub Actions)

CI/CD lives in [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml):

1. **test** — runs `pytest` on every push/PR (uses SQLite, needs no secrets).
2. **deploy** — on push to `main`, after tests pass, it injects the Supabase
   credentials from GitHub secrets into Render (via the Render API) and triggers
   a deploy. Until the Render secrets are set, this step skips cleanly (stays
   green).

**Why the deploy step injects secrets:** GitHub Actions secrets are only
available *during the workflow run*, not to the running app. So the deploy step
pushes `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` into Render's environment, where
the live app reads them at runtime.

### One-time setup

1. **Rotate the Supabase service_role key** (Project Settings → API → reset).
2. **Create the Supabase tables**: run [`supabase_schema.sql`](supabase_schema.sql)
   in the Supabase SQL Editor.
3. **Create the Render service**: in Render, *New → Blueprint*, pick this repo.
   `render.yaml` defines a free web service running `gunicorn app:app`, with
   auto-deploy off (the Action drives deploys). Copy the service's ID
   (`srv-...`) from its URL/settings.
4. **Create a Render API key**: Render Account Settings → API Keys.
5. **Add GitHub repo secrets** (Settings → Secrets and variables → Actions):
   - `RENDER_API_KEY` — the Render API key
   - `RENDER_SERVICE_ID` — the `srv-...` id
   - `SUPABASE_URL` — `https://<ref>.supabase.co`
   - `SUPABASE_SERVICE_KEY` — the (rotated) service_role key
6. Push to `main` → tests run → the app deploys to Render over HTTPS (required
   for the browser geolocation prompt to work).

> The `service_role` key never appears in the repo or in `render.yaml` — it
> lives only in GitHub secrets and, at deploy time, in Render's environment.

## HTTPS note (testing on a phone)

Browsers only allow the Geolocation API on **secure origins**: `https://...`
or `http://localhost`. So:

- On the **same computer**, `http://localhost:5000` works for the share page.
- On a **phone over Wi-Fi**, `http://<your-computer-ip>:5000` will be blocked by
  the browser for geolocation because it is plain HTTP. To test on a phone you
  need HTTPS. Two easy options:
  - Run a tunnel such as `ngrok http 5000` and use the `https://` URL it gives you.
  - Put the app behind a local HTTPS reverse proxy (e.g. `mkcert` + Caddy/nginx).

## Architecture

| File | Role |
|------|------|
| `app.py` | Flask app: routes, token generation, owner-key auth |
| `store.py` | Storage abstraction: SQLite and Supabase backends |
| `db.py` | SQLite connection handling + schema init |
| `schema.sql` | SQLite `sessions` and `locations` tables |
| `supabase_schema.sql` | Same tables for Supabase Postgres (run once) |
| `templates/index.html` | Create-a-link page |
| `templates/share.html` | Labeled consent + location sender |
| `templates/dashboard.html` | Live Leaflet map (creator only) |
| `static/js/*.js` | Front-end for each page |
| `static/css/style.css` | Styling |

### Access model

Each session has two secrets:

- `share_token` — in the link you send; lets that device **post** its own
  location. It cannot read anyone's location.
- `owner_key` — only in your dashboard link; required to **view** locations.

So sharing the link never leaks location data to whoever holds it — only the
holder of the owner key (you) can see the map.

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Create-session page |
| POST | `/api/sessions` | Create a session (`label`, `expiry_minutes`, `max_members`) |
| GET | `/t/<share_token>` | Consent + sender page |
| POST | `/api/sessions/<share_token>/join` | Join as a member (enforces the member cap) |
| POST | `/api/sessions/<share_token>/ping` | Member posts a location fix (needs `member_token`) |
| POST | `/api/sessions/<share_token>/stop` | End the session |
| GET | `/dashboard/<share_token>?key=...` | Live map (owner key required) |
| GET | `/api/sessions/<share_token>/locations?key=...` | Poll for new fixes |
| GET | `/t/<share_token>/qr.svg` | QR code (SVG) encoding the share link |

## Offline / self-hosted map tiles

The dashboard loads Leaflet and OpenStreetMap tiles from a CDN. To run fully
offline, download `leaflet.js` / `leaflet.css` into `static/` and reference them
locally, and point the tile layer at your own tile source.

## Notes

- This is a learning/demo project. Before any real deployment you'd want a
  production WSGI server (gunicorn/waitress), HTTPS, session expiry/cleanup, and
  rate limiting on the ping endpoint.
