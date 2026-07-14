# GTD

A single-user, self-hosted Getting Things Done (GTD) task system: capture → clarify → organize → reflect → engage, with two-way Google Calendar time-blocking, guided review wizards, ntfy push notifications, and a stats page.

Stack: Django 5.x + HTMX + Alpine.js + Tailwind CSS (standalone CLI, no bundler) + PostgreSQL. Single app `core`, no Celery — background work runs via cron-triggered `manage.py` commands. See `CLAUDE.md` and `docs/solution-plan.md` / `docs/design.md` for full architecture and design details.

## Prerequisites

- Python 3.12
- PostgreSQL (dev uses a shared local Postgres instance — see below)
- The Tailwind standalone CLI binary at `.bin/tailwindcss.exe` (only needed if you change styles; the compiled `static/css/app.css` is already committed)

## First-time setup

1. **Create and activate a virtualenv**

   ```
   python -m venv .venv
   .venv/Scripts/activate
   ```

2. **Install dependencies**

   ```
   .venv/Scripts/python.exe -m pip install -r requirements/dev.txt
   ```

   (`dev.txt` pulls in `base.txt`. Use `requirements/prod.txt` instead on a real server — see `deploy/DEPLOY.md`.)

3. **Configure environment**

   ```
   cp .env.example .env
   ```

   Fill in `.env`:
   - `SECRET_KEY` — any random string for local dev.
   - `DATABASE_URL` — points at your Postgres instance (default assumes a `gtd` db/user on `localhost:5432`).
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT` / `FERNET_KEY` — Google Calendar integration. Generate a Fernet key with:
     ```
     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     ```
   - `NTFY_TOPIC` — your ntfy.sh topic for push notifications.
   - `BACKUP_S3_BUCKET` / `DJANGO_LOG_DIR` — prod-only, leave blank for local dev.

   Until the Google and ntfy values are set, those features silently no-op rather than erroring.

4. **Database**

   Postgres is required from day one (Notes full-text search) — don't substitute SQLite. Create the database/role referenced in `DATABASE_URL` if it doesn't already exist, e.g.:

   ```
   createuser gtd
   createdb -O gtd gtd
   ```

5. **Migrate and create an admin user**

   ```
   .venv/Scripts/python.exe manage.py migrate
   .venv/Scripts/python.exe manage.py createsuperuser
   ```

6. **Run the dev server**

   ```
   .venv/Scripts/python.exe manage.py runserver
   ```

   Visit `http://localhost:8000`.

## Running tests

```
.venv/Scripts/python.exe manage.py test core
```

## Rebuilding Tailwind CSS

`static/css/app.css` is a committed, pre-built artifact — `static/css/input.css` is the source. Rebuild after touching any template's Tailwind classes or `tailwind.config.js`:

```
.bin/tailwindcss.exe -i static/css/input.css -o static/css/app.css --minify
```

If `.bin/tailwindcss.exe` is missing, download the Tailwind v3.4.17 standalone binary from its GitHub release for your platform (not v4 — this config uses v3-style `tailwind.config.js` + `safelist`).

## Connecting Google Calendar

With `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_OAUTH_REDIRECT`/`FERNET_KEY` set, go to **Settings → Google Calendar → Connect** in the app and complete the OAuth consent flow. This creates a dedicated "GTD" calendar (write target) and reads your primary calendar as a read-only busy overlay.

For the OAuth client's Google Cloud Console configuration:
- **Authorized redirect URI**: must exactly match `GOOGLE_OAUTH_REDIRECT`, e.g. `http://localhost:8000/google/callback` locally or `https://gtd.sudipto.dev/google/callback` in production.
- **Authorized JavaScript origin**: the same host with no path, e.g. `http://localhost:8000` / `https://gtd.sudipto.dev` (not actually used — this app does a server-side OAuth flow — but harmless to add).

## Notifications (ntfy)

With `NTFY_TOPIC` set, go to **Settings → Notifications** and use the test-fire button to confirm delivery to the ntfy app/topic. Real notifications (missed calendar blocks, review reminders/overdue, follow-up digest, recurring-task overdue) are dispatched by the cron-triggered management commands below, not by the running web server itself.

## Background jobs (cron)

There's no task queue — recurring work runs via `manage.py` commands, meant to be cron-scheduled. For local dev you can invoke any of these manually to test them:

| Command | Purpose | Prod cadence |
|---|---|---|
| `sync_gcal` | Two-way Google Calendar sync (poll fallback) | every 15 min |
| `detect_missed_blocks` | Flag time blocks that passed without completion | every 15 min |
| `renew_gcal_channels` | Renew Google push-notification webhook channels | daily 03:00 |
| `materialize_recurring` | Generate due occurrences from `RecurringTemplate`s | hourly |
| `rollover` | Carry over horizons (today/week/month) at day boundary | daily 00:05 |
| `notify_review_reminders` | T-15min review reminder push | every 5 min |
| `notify_review_overdue` | Nag for overdue reviews | daily 09:00 |
| `notify_follow_up_digest` | Digest of due follow-ups | daily 09:00 |
| `notify_recurring_overdue` | Nag for overdue recurring tasks | daily 09:00 |
| `backup_database` | Dump DB and upload to S3 (no-op if `BACKUP_S3_BUCKET` unset) | daily 02:00 |

Date/time-sensitive commands accept overrides for testing, e.g. `--as-of YYYY-MM-DD` or `--now <ISO datetime>`.

The full production crontab is in `deploy/crontab.txt`.

## Deploying to production

See `deploy/DEPLOY.md` for the full manual checklist (EC2 provisioning, nginx, systemd, certbot, cron install, S3 backups, post-deploy smoke test). `deploy/gtd.service` and `deploy/nginx-gtd.conf` are the systemd/nginx config templates.

## Known gaps

- `static/fonts/` is empty (Bricolage Grotesque, Inter, JetBrains Mono `.woff2` files not sourced) — falls back to system fonts.
- PWA icons (`icon-192.png`, `icon-512.png`) referenced by the manifest aren't generated yet — "Add to Home Screen" will use a broken icon until they exist.

See `CLAUDE.md` for the full epic-by-epic build log and caveats.
