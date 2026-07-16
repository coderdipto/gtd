# Deploying GTD (bare-metal / VM)

This is the manual checklist for a traditional server deploy (Ubuntu + gunicorn
+ nginx + systemd + cron). If you just want to run it, `docker compose up` is
far quicker — see the README. Replace `gtd.example.com` with your own domain
throughout, and `/home/gtd/app` if you install elsewhere.

The app-side pieces referenced below — the systemd unit, nginx config, cron
table, `backup_database`/logging config — all already exist in this repo and
are covered by the test suite. Provisioning the server, DNS, and TLS cert is
the part only you can do.

## 1. Server + OS

1. Launch a VM running Ubuntu.
2. `apt install python3.12-venv postgresql nginx certbot python3-certbot-nginx`.
3. Create a dedicated `gtd` system user; app lives at `/home/gtd/app`.
4. `git clone` this repo there, create `.venv`, `pip install -r requirements/prod.txt`.
5. Copy `.env.example` to `.env`, fill in real values (`SECRET_KEY`, `DATABASE_URL`,
   `ALLOWED_HOSTS=gtd.example.com`, `DEBUG=False`, optionally `GOOGLE_*`,
   `FERNET_KEY`, `NTFY_TOPIC`, `BACKUP_S3_BUCKET`, `DJANGO_LOG_DIR=/var/log/gtd`).
   Never commit this file. Generate a key with
   `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
6. `mkdir -p /var/log/gtd /var/lib/gtd` (or wherever `DJANGO_LOG_DIR` points), owned by `gtd`.

## 2. Database

1. Create a local Postgres role/database matching `DATABASE_URL`.
2. `manage.py migrate`.
3. `manage.py createsuperuser` (one-time — this is a single-user app).

## 3. Static files

`manage.py collectstatic --noinput` → populates `staticfiles/`, which
`nginx-gtd.conf`'s `location /static/` serves directly.

## 4. systemd + nginx (manual, one-time)

1. Copy `deploy/gtd.service` to `/etc/systemd/system/gtd.service`, adjust
   paths/user if they differ from `/home/gtd/app`. `systemctl enable --now gtd`.
2. Copy `deploy/nginx-gtd.conf` to `/etc/nginx/sites-available/gtd`, symlink
   into `sites-enabled`, `nginx -t && systemctl reload nginx`.
3. **DNS**: point `gtd.example.com` at the server's IP (A record) via your
   domain's DNS provider.
4. **TLS**: `certbot --nginx -d gtd.example.com` (also handles the cert
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

- `https://gtd.example.com/` redirects to login, then to Today after auth.
- Settings → Google Calendar "Connect" completes the real OAuth round-trip.
- Settings → Notifications "Test" button delivers a real ntfy push.
- Upload a Note attachment, confirm the download link works (this is the
  `X-Accel-Redirect` path — if it 404s, check `nginx -T` for the
  `/protected-media/` location block and that `alias` matches `MEDIA_ROOT`).
