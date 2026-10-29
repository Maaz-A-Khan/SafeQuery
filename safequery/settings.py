"""Django settings for SafeQuery.

Secrets come from `.env` only (NFR-S4). Agent thresholds are in `SAFEQUERY`.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from agent.config import AgentConfig, GeminiConfig

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"{name} is missing. Copy .env.example to .env and fill it in.")
    return value


SECRET_KEY = _require("DJANGO_SECRET_KEY")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Local only (NFR-S7): Connect and Ask have no login. LocalOnlyMiddleware is the real
# guard; ALLOWED_HOSTS checks the Host header, which a client chooses.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "core.middleware.LocalOnlyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "safequery.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.current_connection",
            ],
        },
    },
]

WSGI_APPLICATION = "safequery.wsgi.application"

# The app's own PostgreSQL database. Never the same database or account as a target (NFR-S5).
DATABASES = {"default": dj_database_url.parse(_require("DATABASE_URL"))}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "log"
LOGOUT_REDIRECT_URL = "connect"

# --- SafeQuery ---------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
FERNET_KEY = os.environ.get("FERNET_KEY", "")           # needed from Phase 5

# Thresholds: timeout, row cap, join limit, cost ceiling, lists. See agent/config.py.
SAFEQUERY = AgentConfig(
    gemini=GeminiConfig(model=os.environ.get("GEMINI_MODEL", GeminiConfig.model), api_key=GEMINI_API_KEY),
)
