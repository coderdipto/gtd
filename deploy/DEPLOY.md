# Deploying GTD (docs/task-breakdown.md Epic 12)

Everything in this directory (`gtd.service`, `nginx-gtd.conf`, `crontab.txt`) is
generated/reviewed by the coding agent, but **provisioning the actual server,
DNS, and TLS cert is a manual, one-time task only the user can do** — same
category of blocker as Epic 8's Google Cloud Console setup. This file is the
checklist for that manual part; everything it references from the app side
(the systemd unit, nginx config, cron table, `backup_database`/logging config)
already exists in this repo and is unit-tested.

## 1. EC2 + OS

1. Launch an EC2 instance running Ubuntu (same pattern as `tracker.sudipto.dev`).
2. `apt install python3.12-venv postgresql nginx certbot python3-certbot-nginx`.
3. Create a dedicated `gtd` system user; app lives at `/home/gtd/app`.
4. `git clone` this repo there, create `.venv`, `pip install -r requirements/prod.txt`.
5. Copy `.env.example` to `.env`, fill in real values (`SECRET_KEY`, `DATABASE_URL`,
   `ALLOWED_HOSTS=gtd.sudipto.dev`, `GOOGLE_*`, `FERNET_KEY`, `NTFY_TOPIC`,
   `BACKUP_S3_BUCKET`, `DJANGO_LOG_DIR=/var/log/gtd`). Never commit this file.
6. `mkdir -p /var/log/gtd /var/lib/gtd` (or wherever `DJANGO_LOG_DIR` points), owned by `gtd`.

## 2. Database

1. Create a local Postgres role/database matching `DATABASE_URL`.
2. `manage.py migrate`.
3. `manage.py createsuperuser` (one-time, matches the existing single-user setup).

## 3. Static files

`manage.py collectstatic --noinput` → populates `staticfiles/`, which
`nginx-gtd.conf`'s `location /static/` serves directly.

## 4. systemd + nginx (manual, one-time)

1. Copy `deploy/gtd.service` to `/etc/systemd/system/gtd.service`, adjust
   paths/user if they differ from `/home/gtd/app`. `systemctl enable --now gtd`.
2. Copy `deploy/nginx-gtd.conf` to `/etc/nginx/sites-available/gtd`, symlink
   into `sites-enabled`, `nginx -t && systemctl reload nginx`.
3. **DNS**: point `gtd.sudipto.dev` at the EC2 instance's IP (A record) — the
   agent cannot do this; needs access to the domain's DNS provider.
4. **TLS**: `certbot --nginx -d gtd.sudipto.dev` (also handles the cert
   paths already referenced in `nginx-gtd.conf`, and sets up its own renewal
   timer — no cron entry needed for that part).

## 5. Cron

`crontab -u gtd deploy/crontab.txt` (edit the `MANAGE=` path first if the app
isn't at `/home/gtd/app`).

## 6. Backups

Create an S3 bucket, set `BACKUP_S3_BUCKET` in `.env`, and either attach an
IAM role with write access to the EC2 instance (preferred — no long-lived
keys on the box) or set `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. The
`backup_database` cron entry above handles the rest (nightly dump + 14-day
S3 retention).

## 7. Smoke test after deploy

- `https://gtd.sudipto.dev/` redirects to login, then to Today after auth.
- Settings → Google Calendar "Connect" completes the real OAuth round-trip.
- Settings → Notifications "Test" button delivers a real ntfy push.
- Upload a Note attachment, confirm the download link works (this is the
  `X-Accel-Redirect` path — if it 404s, check `nginx -T` for the
  `/protected-media/` location block and that `alias` matches `MEDIA_ROOT`).
