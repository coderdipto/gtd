"""
Django settings for gtd project.
"""

import os
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# True while the test suite is loading settings — under `manage.py test`
# ("test" in argv) or pytest (imports settings during collection, after the
# `pytest` module is already imported). Used to keep dev-only, request-time
# instrumentation (django-debug-toolbar) out of test runs: the runner forces
# DEBUG=False after settings import, so the toolbar would otherwise activate
# under any @override_settings(DEBUG=True) test while its URLs are unregistered.
TESTING = ("test" in sys.argv) or ("pytest" in sys.modules)

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-change-me")

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])


# Application definition

INSTALLED_APPS = [
    # Must precede django.contrib.admin: its templates only override the
    # built-in admin's if Django's app-dirs template loader finds them first.
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Views that must stay reachable without login: GCal webhook + capture API
# (see core/views.py — decorated with @login_not_required).
LOGIN_URL = "login"
# Django's default post-login target is /accounts/profile/, which doesn't
# exist here (404). Send freshly-authenticated users to their Today list.
LOGIN_REDIRECT_URL = "today"

ROOT_URLCONF = "gtd.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.trust_strip",
            ],
        },
    },
]

WSGI_APPLICATION = "gtd.wsgi.application"


# Database
# Postgres required from day one (Postgres FTS needed for Notes search — see solution-plan.md).

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://gtd:gtd@localhost:5432/gtd"),
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# All dates/times render in Asia/Dhaka (see docs/design.md §8).

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Dhaka"

USE_I18N = True

USE_TZ = True


# Django Unfold admin theme (/admin/ only - no effect on the main app,
# which has its own design system per docs/design.md). Color ramp is a hand
# extrapolation of the app's own paper/water/ink tokens (tailwind.config.js)
# so the admin doesn't look like a jarring third palette.
UNFOLD = {
    "SITE_TITLE": "GTD Admin",
    "SITE_HEADER": "GTD",
    "SITE_SYMBOL": "checklist",
    "COLORS": {
        "primary": {
            "50": "253 246 240",
            "100": "250 231 219",
            "200": "244 208 189",
            "300": "235 174 143",
            "400": "219 128 91",
            "500": "190 81 51",
            "600": "163 66 41",
            "700": "130 53 33",
            "800": "97 40 25",
            "900": "68 29 19",
            "950": "42 18 27",
        },
    },
}

# Static files (CSS, JavaScript, Images)

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media (Notes attachments — served privately via nginx X-Accel-Redirect in prod, see Step 12)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Settings hygiene (lesson from tracker.sudipto.dev): DEBUG must be False in prod,
# no django-browser-reload in prod requirements. See requirements/ split.

# Google Calendar (Step 8). All blank by default - every GCal call in
# core/google_calendar.py is gated on a connected GoogleCredential existing,
# so an unconfigured install just shows "Not connected" and does nothing.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")
GOOGLE_OAUTH_REDIRECT = env("GOOGLE_OAUTH_REDIRECT", default="http://localhost:8000/google/callback")
# Fernet key encrypting GoogleCredential.refresh_token at rest. Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY = env("FERNET_KEY", default="")

# ntfy (Step 10). Blank by default - core/notifications.py::notify() is a
# no-op without a topic. Pick a high-entropy topic name (same practice as
# claude-watch) since anyone who knows it can read/publish to it - it's not
# a secret in the cryptographic sense, but treat it like one.
NTFY_TOPIC = env("NTFY_TOPIC", default="")

# Logging (Step 12): console always; a rotating file handler is added only in
# prod (DEBUG=False) - gunicorn's own stdout/stderr already goes to the
# systemd journal (see deploy/gtd.service), so this file is specifically for
# Django-level messages (sync errors etc., logged with an event id - see
# core/google_calendar.py's logger.error(..., extra={"event_id": ...}) calls).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

if not DEBUG:
    # WhiteNoise (prod-only, see requirements/prod.txt): content-hashed static
    # files with far-future cache headers, so a rebuilt app.css can never serve
    # stale from browser cache. Middleware goes directly after SecurityMiddleware
    # per WhiteNoise's docs; the storage backend gzip/brotli-compresses and
    # fingerprints every file at collectstatic time. Gated on `not DEBUG` so a
    # dev checkout (which serves static via the staticfiles app and has no
    # collected manifest) is unaffected and doesn't need whitenoise installed.
    MIDDLEWARE.insert(
        MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
        "whitenoise.middleware.WhiteNoiseMiddleware",
    )
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

    LOG_DIR = env("DJANGO_LOG_DIR", default=str(BASE_DIR / "logs"))
    os.makedirs(LOG_DIR, exist_ok=True)
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": os.path.join(LOG_DIR, "gtd.log"),
        "maxBytes": 10 * 1024 * 1024,
        "backupCount": 5,
        "formatter": "verbose",
    }
    LOGGING["root"]["handlers"].append("file")

# django-debug-toolbar (dev-only, see requirements/dev.txt). Guarded on the
# import so a prod checkout — which never installs it — just skips this block.
# Surfaces the per-request query count that would have caught the list-view
# N+1s, and guards against new ones regressing as more list views land.
# Skipped under TESTING so an @override_settings(DEBUG=True) test can't trip the
# middleware into rendering against URLs that were never registered.
if DEBUG and not TESTING:
    try:
        import debug_toolbar  # noqa: F401
    except ImportError:
        pass
    else:
        INSTALLED_APPS.append("debug_toolbar")
        # As early as possible per the toolbar's docs (nothing here encodes the
        # response body — GZip/WhiteNoise are prod-only — so the top is safe).
        MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
        INTERNAL_IPS = ["127.0.0.1"]
