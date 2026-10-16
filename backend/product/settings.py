import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DEBUG=(bool, False),
    CRAWLER_RESPECT_ROBOTS=(bool, True),
    CRAWLER_MAX_DEPTH=(int, 2),
    CRAWLER_MAX_PAGES=(int, 50),
    CRAWLER_TIMEOUT_SECONDS=(int, 15),
    CRAWLER_MAX_CONTENT_BYTES=(int, 2_000_000),
)
environ.Env.read_env(os.environ.get("ENV_FILE", BASE_DIR.parent / ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-local-development-key")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "product_api",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "product.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "product.wsgi.application"
ASGI_APPLICATION = "product.asgi.application"

database_url = env("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {"default": env.db_url_config(database_url)}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["CONN_MAX_AGE"] = 60

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
MEDIA_URL = "media/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/hour",
        "user": "1200/hour",
        "widget": "30/hour",
    },
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Personal AI Assistant Platform API",
    "DESCRIPTION": "Owner-authenticated dashboard API and rate-limited public widget API.",
    "VERSION": "1.0.0",
}
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

AI_BACKEND_BASE_URL = env("AI_BACKEND_BASE_URL", default="http://host.docker.internal:8001").rstrip("/")
AI_BACKEND_API_KEY = env("AI_BACKEND_API_KEY", default="")
AI_DEFAULT_MODEL = env("AI_DEFAULT_MODEL", default="")
AI_TIMEOUT_SECONDS = env.int("AI_TIMEOUT_SECONDS", default=60)
RAG_CORE_BASE_URL = env("RAG_CORE_BASE_URL", default="http://host.docker.internal:8000").rstrip("/")
RAG_CORE_API_KEY = env("RAG_CORE_API_KEY", default="")
RAG_TIMEOUT_SECONDS = env.int("RAG_TIMEOUT_SECONDS", default=60)
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:3000")
WIDGET_ALLOWED_ORIGINS = env.list("WIDGET_ALLOWED_ORIGINS", default=[])
TELEGRAM_WEBHOOK_BASE_URL = env("TELEGRAM_WEBHOOK_BASE_URL", default="")
CREDENTIAL_ENCRYPTION_KEY = env("CREDENTIAL_ENCRYPTION_KEY", default=SECRET_KEY)
if not DEBUG and SECRET_KEY == "unsafe-local-development-key":
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG=False.")
if not DEBUG and CREDENTIAL_ENCRYPTION_KEY.startswith("replace-with-"):
    raise ImproperlyConfigured("Set a stable CREDENTIAL_ENCRYPTION_KEY when DEBUG=False.")

CRAWLER_EXTRACTOR = env("CRAWLER_EXTRACTOR", default="local")
CRAWLER_FALLBACK = env("CRAWLER_FALLBACK", default="")
CRAWLER_MAX_DEPTH = env("CRAWLER_MAX_DEPTH")
CRAWLER_MAX_PAGES = min(env.int("CRAWLER_MAX_PAGES"), 500)
CRAWLER_RESPECT_ROBOTS = env("CRAWLER_RESPECT_ROBOTS")
CRAWLER_TIMEOUT_SECONDS = env("CRAWLER_TIMEOUT_SECONDS")
CRAWLER_MAX_CONTENT_BYTES = env("CRAWLER_MAX_CONTENT_BYTES")
CRAWLER_USER_AGENT = env("CRAWLER_USER_AGENT", default="PersonalAIBot/1.0")
JINA_API_KEY = env("JINA_API_KEY", default="")
JINA_API_BASE_URL = env("JINA_API_BASE_URL", default="https://r.jina.ai/")
FIRECRAWL_API_KEY = env("FIRECRAWL_API_KEY", default="")
FIRECRAWL_API_BASE_URL = env("FIRECRAWL_API_BASE_URL", default="https://api.firecrawl.dev")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

if CRAWLER_MAX_DEPTH < 0 or CRAWLER_MAX_PAGES < 1 or CRAWLER_TIMEOUT_SECONDS < 1 or CRAWLER_MAX_CONTENT_BYTES < 1:
    raise ValueError("Crawler limits must be positive; CRAWLER_MAX_DEPTH may be zero.")
if CRAWLER_EXTRACTOR not in {"local", "jina", "firecrawl"}:
    raise ValueError("CRAWLER_EXTRACTOR must be local, jina, or firecrawl.")
if CRAWLER_FALLBACK not in {"", "local", "jina", "firecrawl"}:
    raise ValueError("CRAWLER_FALLBACK must be empty, local, jina, or firecrawl.")
