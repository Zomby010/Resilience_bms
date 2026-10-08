"""
Django settings for the RESILIENCE Business Management System.

Configuration comes from environment variables (see .env.example) so the same
code runs locally and in production. Nothing secret lives in this file.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Read KEY=VALUE lines from a local .env file (real environment variables win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = _env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Development only: a throwaway key so `runserver` works out of the box.
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise RuntimeError("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development).")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "reports",
    "finance",
    "core",
    "tracking",
    "notifications",
    "escalations",
    "clients",
    "billing",
    "payroll",
    "inventory",
    "incidents",
    "leave",
    "attendance",
    "operations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "tracking.middleware.LastSeenMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "tracking.context_processors.location_reminder",
                "notifications.context_processors.bell",
            ],
            "builtins": ["core.templatetags.ui"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite keeps local setup to zero steps. In production use PostgreSQL, given either as one
# DATABASE_URL (what Neon and Vercel's Neon integration provide) or as the separate DB_* variables.
if os.environ.get("DATABASE_URL"):
    from urllib.parse import parse_qs, urlparse

    _db_url = urlparse(os.environ["DATABASE_URL"])
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _db_url.path.lstrip("/"),
            "USER": _db_url.username,
            "PASSWORD": _db_url.password,
            "HOST": _db_url.hostname,
            "PORT": str(_db_url.port or 5432),
            "OPTIONS": {"sslmode": parse_qs(_db_url.query).get("sslmode", ["require"])[0]},
        }
    }
elif os.environ.get("DB_ENGINE") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ["DB_USER"],
            "PASSWORD": os.environ["DB_PASSWORD"],
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "OPTIONS": {"sslmode": os.environ.get("DB_SSLMODE", "prefer")},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    # Neon's pooled connections (PgBouncer) don't keep server-side cursors between queries.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files (attachments, receipts, company logo, sick sheets). Never served directly:
# downloads go through a view that checks the person may see the record the file belongs to.
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))
# Vercel refuses requests over 4.5 MB, so uploads stay under 4 MB (see core.models.MAX_UPLOAD_BYTES).
FILE_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024 + 256 * 1024

# Hosted (Vercel has no lasting disk): with AWS_ENDPOINT_URL_S3 set, files go to private Neon buckets,
# sick sheets in their own bucket. The AWS_* names are the ones `neon env pull` writes.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
if os.environ.get("AWS_ENDPOINT_URL_S3"):
    def _bucket(name):
        return {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": name,
                "endpoint_url": os.environ["AWS_ENDPOINT_URL_S3"],
                "region_name": os.environ.get("AWS_REGION", ""),
                "addressing_style": "path",
                "signature_version": "s3v4",
                "default_acl": None,
                "file_overwrite": False,
            },
        }

    STORAGES["default"] = _bucket(os.environ.get("UPLOADS_BUCKET", "uploads"))
    STORAGES["sicksheets"] = _bucket(os.environ.get("SICKSHEETS_BUCKET", "sicksheets"))

# Vercel Cron calls /cron/daily/ with this secret; without it the address does not exist.
CRON_SECRET = os.environ.get("CRON_SECRET", "")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Fast password hashing for the test suite only (never used in real runs).
import sys  # noqa: E402

if "test" in sys.argv[1:2]:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Application-specific
CURRENCY = "KES"

# Email. Without EMAIL_HOST nothing is sent: in development emails are printed to the console,
# and on a live site (DEBUG off) every send fails with a clear "email is not set up" message, so a
# client message is never marked as sent when it wasn't. A real provider is set up only after the
# owner approves one (Gate 7). Tests always use memory.
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", True)
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "core.services.mail.NotConfiguredBackend"
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Resilience BMS <no-reply@localhost>")

# Hardened defaults whenever DEBUG is off.
if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
