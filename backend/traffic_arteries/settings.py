"""Django settings for traffic_arteries.

Route/graph data lives in the R2 object store (``api/db.py`` + ``utils/r2_storage``);
the ``accounts`` app uses the real ORM/database (SQLite locally, Neon Postgres in
production) for users. Config is environment-driven with local-dev fallbacks: a
git-ignored ``backend/.env`` (see ``.env.example``) is loaded on startup, so
running locally needs no exported vars. In production (Cloudflare Pages frontend +
Render backend) the two live on different origins, so CORS is configured below.
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env (if present) before reading any os.environ config below.
load_dotenv(BASE_DIR / ".env")

# Local directory of the JSON seed files, used only by the `seed_r2` command to
# populate the bucket. The live store is in R2, not here.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DATA_DIR = os.path.abspath(DATA_DIR)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secret-change-in-production")
# Prod-safe default; a local .env sets DEBUG=True for development.
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS", "localhost,127.0.0.1,traffic-arteries.onrender.com"
).split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "api",
    "accounts",
]

MIDDLEWARE = [
    # WhiteNoise serves collected static files (admin/DRF) under DEBUG=False.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CORS must sit above CommonMiddleware to annotate cross-origin responses.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "traffic_arteries.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    },
]

WSGI_APPLICATION = "traffic_arteries.wsgi.application"

# Route/graph data lives in R2, but user accounts are real ORM-backed rows.
# Uses DATABASE_URL (Neon Postgres) in production; falls back to local SQLite.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

# Cross-origin access from the Cloudflare Pages frontend (unused in dev, where the
# Vite proxy keeps everything same-origin).
CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS", "https://traffic-arteries.pages.dev"
).split(",")
# Trusted origins for CSRF-checked POSTs (e.g. the admin login) under DEBUG=False.
CSRF_TRUSTED_ORIGINS = [
    "https://traffic-arteries.onrender.com",
    "https://traffic-arteries.pages.dev",
]

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

LANGUAGE_CODE = "he"
TIME_ZONE = "Asia/Jerusalem"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise's compressed+hashed manifest storage in production; the plain
# default in dev (runserver serves via finders, and the manifest would otherwise
# require a collectstatic run first).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
