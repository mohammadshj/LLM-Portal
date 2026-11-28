import os
import json
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
BRAND_DIR = BASE_DIR / "brand"
if not BRAND_DIR.is_dir():
    BRAND_DIR = BASE_DIR.parent / "frontend/public/brand"
PORTAL_BRAND = json.loads((BRAND_DIR / "settings.json").read_text())
STATICFILES_DIRS = [("brand", BRAND_DIR)]
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before starting Django.")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [
    v for v in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if v
]
INSTALLED_APPS = [
    "config.apps.PortalAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "portal",
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
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
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
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "portal"),
        "USER": os.getenv("POSTGRES_USER", "portal"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}
# Explicit opt-in for local smoke tests only; production uses PostgreSQL.
if os.getenv("PORTAL_SQLITE_TEST") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "local.sqlite3",
        }
    }
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}
LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# Legacy endpoint is read only when migration 0003 creates the default connection.
# New endpoints live in ModelConnection; keys are resolved from the environment.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")

# Seconds. The read timeout is the longest idle interval between upstream bytes.
LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "10"))
LLM_READ_TIMEOUT = float(os.getenv("LLM_READ_TIMEOUT", "90"))
LLM_TOTAL_TIMEOUT = float(os.getenv("LLM_TOTAL_TIMEOUT", "300"))

# Exact trusted origins for private/loopback catalog servers. Metadata and
# link-local destinations remain blocked even for a listed origin.
DISCOVERY_LOCAL_ORIGINS = frozenset(
    origin.strip().rstrip("/")
    for origin in os.getenv("LLM_DISCOVERY_LOCAL_ORIGINS", "").split(",")
    if origin.strip()
)

DISCOVERY_REGISTRY_OFFLINE = (
    os.getenv("LLM_DISCOVERY_REGISTRY_OFFLINE", "").lower() == "true"
)
