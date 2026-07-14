"""
Django settings for gtd project.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-change-me")

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])


# Application definition

INSTALLED_APPS = [
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
