#!/bin/sh
# Apply DB migrations, then hand off to the container's main command (gunicorn).
# The db healthcheck in docker-compose.yml gates start until Postgres is ready.
set -e

python manage.py migrate --noinput

exec "$@"
