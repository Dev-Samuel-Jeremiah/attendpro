"""
AttendPro — QR attendance management for organisations and schools.
Built by Techmiary Technology Concepts.
"""
from pathlib import Path

from decouple import Config, Csv, RepositoryEmpty, RepositoryEnv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Settings come from environment variables, then from .env next to manage.py
# (see .env.example). With no .env at all, the defaults suit local development.
_env_file = BASE_DIR / ".env"
config = Config(RepositoryEnv(str(_env_file)) if _env_file.exists() else RepositoryEmpty())

_DEV_SECRET_KEY = "change-me-in-production-attendpro-dev-key"
DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)
SECRET_KEY = config("DJANGO_SECRET_KEY", default=_DEV_SECRET_KEY)
if not DEBUG and SECRET_KEY == _DEV_SECRET_KEY:
    # The key also signs the reception QR codes, so a known key would let anyone forge scans.
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a long random value when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="*" if DEBUG else "", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# Django's built-in admin (platform super-admin). Use a hard-to-guess path in production.
ADMIN_URL = config("DJANGO_ADMIN_URL", default="django-admin/").strip("/") + "/"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "billing",
    "leave",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "attendpro.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.organisation",
                "billing.context_processors.plan",
                "notifications.context_processors.unread",
            ],
        },
    },
]

WSGI_APPLICATION = "attendpro.wsgi.application"

# SQLite for local development; PostgreSQL in production (DB_ENGINE=postgresql).
if config("DB_ENGINE", default="sqlite") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = config("DJANGO_TIME_ZONE", default="Africa/Lagos")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = config("DJANGO_STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))

# In production, collectstatic adds a content hash to each file name (app.3f9a1c.css), so
# browsers fetch new CSS/JS right after a deploy despite nginx's long cache headers.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage." + (
        "StaticFilesStorage" if DEBUG else "ManifestStaticFilesStorage")},
}

MEDIA_URL = "media/"
MEDIA_ROOT = config("DJANGO_MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Keep staff signed in on their phones for 30 days so scanning is one tap.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

# Base URL encoded in the reception QR (e.g. "http://192.168.0.10:8000").
# Leave blank to use whatever address the reception screen was opened with.
ATTENDPRO_PUBLIC_URL = config("ATTENDPRO_PUBLIC_URL", default="").rstrip("/")

# Paystack (online plan payments). Leave blank to switch online payment off.
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")

# Email (automated notifications). Leave EMAIL_HOST blank to send in-app notifications only.
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="AttendPro <no-reply@attendpro.cloud>")

# HTTPS hardening. Nginx terminates TLS and tells Django via X-Forwarded-Proto.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start at 30 days; raise to a year once HTTPS has been stable for a while.
    SECURE_HSTS_SECONDS = config("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 30, cast=int)

# Errors and warnings go to the console (journald on the server: journalctl -u attendpro).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
