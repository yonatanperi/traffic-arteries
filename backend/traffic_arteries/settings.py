"""Django settings for traffic_arteries.

Minimal setup: no database models are used (storage is the filesystem JSON
store in ``api/db.py``), so the ORM/migrations machinery is left at defaults but
never exercised. CORS is unnecessary because the Vite dev server proxies /api.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DATA_DIR = os.path.abspath(DATA_DIR)

SECRET_KEY = "dev-only-not-secret-change-in-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "api",
    "core",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "traffic_arteries.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "traffic_arteries.wsgi.application"

# The app stores data on the filesystem, but Django still wants a DATABASES
# entry. Point it at an in-memory sqlite so nothing is written to disk.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# No auth/sessions/contrib.auth are installed — this is a public, single-user
# filesystem-backed API consumed by the SPA, so DRF runs fully standalone.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    # Without contrib.auth installed, don't let DRF import AnonymousUser.
    "UNAUTHENTICATED_USER": None,
}

LANGUAGE_CODE = "he"
TIME_ZONE = "Asia/Jerusalem"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
