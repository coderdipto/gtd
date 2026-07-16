# GTD

A **single-user, self-hosted** [Getting Things Done](https://gettingthingsdone.com/)
task system — capture → clarify → organize → reflect → engage — with two-way
Google Calendar time-blocking, guided review wizards, an Eisenhower triage board,
natural-language capture, push notifications, and a stats page.

Built with Django + HTMX + Alpine.js + Tailwind, in a warm, editorial style. No
JavaScript build step, no background queue — just Postgres and cron.

[![CI](https://github.com/coderdipto/gtd/actions/workflows/ci.yml/badge.svg)](https://github.com/coderdipto/gtd/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Django 5.1](https://img.shields.io/badge/django-5.1-092e20.svg)

> **This is a single-tenant app.** One deployment holds one person's data — there
> is no per-user separation. Great for running your own instance; **not** a
> multi-user service. See [SECURITY.md](SECURITY.md) before exposing it.

## Screenshots

| Engage — what can I do now? | Clarify wizard |
| :-: | :-: |
| ![Engage view](docs/screenshots/engage.png) | ![Clarify wizard](docs/screenshots/clarify.png) |
| **Today** | **Project detail** |
| ![Today](docs/screenshots/today.png) | ![Project detail](docs/screenshots/project.png) |

## Features

- **Capture** — a friction-free inbox (web, quick-capture modal, or an iOS
  Shortcut via a token API). Offline captures queue in a service worker and sync
  on reconnect. Natural-language dates: type *"Call plumber tomorrow 3pm"* and it
  pre-fills the due date.
- **Clarify** — a guided wizard walks each inbox item through the GTD decision
  tree (actionable? project? delegate? someday? reference?) with keyboard
  shortcuts. Bulk-process several at once.
- **Organize** — projects with one-level subtasks and automatic next-action
  resolution, contexts/tags (`@calls`, `#urgent`), horizons (today / this week /
  this month / anytime), manual drag ordering, areas of focus, and reusable
  **project templates**.
- **Reflect** — guided weekly/monthly review wizards, an **Eisenhower** triage
  board (drag-only, review-time only), Big-3 stars, and a carry-over gate. Plus a
  stats page.
- **Engage** — a "what can I do right now?" view that filters next actions by
  **context × available time × energy**, with one-tap presets.
- **Calendar** — time-block any task; drag Today's tasks straight onto the
  calendar. Optional **two-way Google Calendar** sync to a dedicated calendar.
- **Notes** — Markdown notes with Postgres full-text search, attachments, and
  links to the project/task they support.
- **Notifications** — optional [ntfy](https://ntfy.sh) push for missed blocks,
  review reminders, and follow-up digests.
- **Command palette** — `⌘K` / `Ctrl-K` to jump anywhere or capture instantly.
- **PWA** — installable, works as an app shell.

Everything except the two integrations (Google Calendar, ntfy) works fully
offline/local — leave those unconfigured and the app simply runs local-only.

## Tech stack

Django 5.1 · HTMX · Alpine.js · Tailwind CSS (standalone CLI, output committed) ·
PostgreSQL · gunicorn + WhiteNoise. Single Django app (`core`). Background work
runs via cron-triggered `manage.py` commands — no Celery or message queue.

## Quick start (Docker)

The fastest way to try it. Requires Docker.

```bash
git clone https://github.com/coderdipto/gtd.git
cd gtd
docker compose up --build          # starts Postgres + the app on :8000
docker compose exec web python manage.py seed_demo   # optional demo data
```

Open <http://localhost:8000> and log in as **`demo` / `demo`** (if you seeded),
or create your own account:

```bash
docker compose exec web python manage.py createsuperuser
```

The Compose stack is self-contained and runs with `DEBUG=False`. **Change
`SECRET_KEY` in `docker-compose.yml` before exposing it beyond localhost.**

## Quick start (native)

Requires **Python 3.12** and **PostgreSQL** (SQLite is not supported — the app
uses Postgres full-text search).

```bash
git clone https://github.com/coderdipto/gtd.git
cd gtd

python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt

cp .env.example .env                 # then edit DATABASE_URL to match your Postgres
python manage.py migrate
python manage.py seed_demo           # optional: demo login + sample data
python manage.py runserver
```

Open <http://localhost:8000>.

## Configuration

All configuration is via environment variables (a `.env` file works in dev — it
is git-ignored, never commit it). See [`.env.example`](.env.example).

| Variable | Required | Description |
| --- | :-: | --- |
| `SECRET_KEY` | prod | Django secret. App refuses to boot with `DEBUG=False` and the insecure default. Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | | `True` in dev, `False` in prod. |
| `ALLOWED_HOSTS` | prod | Comma-separated hostnames. |
| `DATABASE_URL` | ✓ | e.g. `postgres://gtd:gtd@localhost:5432/gtd` |
| `CSRF_TRUSTED_ORIGINS` | | Needed when accessed via a tunnel (ngrok, etc.). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` | | Google Calendar sync. Blank = disabled. |
| `FERNET_KEY` | | Encrypts the stored Google refresh token. Required only if using Calendar. |
| `NTFY_TOPIC` | | ntfy topic for push notifications. Blank = disabled. Treat as a secret. |
| `BACKUP_S3_BUCKET` / `BACKUP_S3_PREFIX` | | Nightly DB backup to S3 (prod). Blank = no-op. |
| `DJANGO_LOG_DIR` | | Rotating log file dir in prod. |

### Optional integrations

- **Google Calendar** — create OAuth web credentials in the Google Cloud
  Console, enable the Calendar API, set the `GOOGLE_*` vars and a `FERNET_KEY`,
  then connect from the Settings page. Until then, time-blocks stay local-only.
- **ntfy push** — pick a long, random `NTFY_TOPIC`, subscribe to it in the
  [ntfy](https://ntfy.sh) app, and the cron notifiers will push to it.

## Deployment

`docker compose` is enough for a small personal deployment behind a reverse
proxy. For a traditional VM setup (gunicorn + nginx + systemd + cron + TLS),
see [`deploy/DEPLOY.md`](deploy/DEPLOY.md) and the config templates in `deploy/`.

The scheduled jobs (missed-block detection, review reminders, recurrence
materialization, backups) run as cron commands — see
[`deploy/crontab.txt`](deploy/crontab.txt).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, running tests, and the
Tailwind rebuild step. Architecture and design docs live in
[`docs/`](docs/); `CLAUDE.md` is a detailed map of conventions and gotchas.

## License

[MIT](LICENSE) © Sudipto Das
