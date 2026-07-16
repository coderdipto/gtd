# GTD — production-ish image (gunicorn + WhiteNoise-served static).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# postgresql-client is only needed by the optional `backup_database` command
# (pg_dump); psycopg[binary] ships its own libpq, so nothing else is required.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt

COPY . .

# Collect + fingerprint static assets into the image (WhiteNoise serves them at
# runtime). SECRET_KEY here is a throwaway used only so the DEBUG=False settings
# import passes; the real key is supplied at run time via the environment.
RUN SECRET_KEY=build-only-not-a-runtime-key DEBUG=False DJANGO_LOG_DIR=/tmp \
    python manage.py collectstatic --noinput

EXPOSE 8000
ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "gtd.wsgi:application"]
