"""Growth IA — Django settings. Every value comes from the environment (see /.env.example)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent


def env(name: str, default: str | None = None) -> str:
    return os.environ.get(name, default if default is not None else "")


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("insecure-dev-only" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
APP_VERSION = env("APP_VERSION", "0.1.0")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "django_celery_beat",
    # Growth IA — foundation
    "apps.core", "apps.accounts", "apps.tenants", "apps.memberships", "apps.invitations",
    "apps.permissions", "apps.licensing", "apps.integrations", "apps.notifications",
    "apps.products", "apps.websites", "apps.scheduler", "apps.reporting", "apps.audit",
    "apps.history", "apps.observability", "apps.system_health", "apps.ai_providers",
    # Growth IA — business modules (schema ready, features in later prompts)
    "apps.seo", "apps.geo", "apps.content", "apps.social", "apps.opportunities",
    "apps.prospects", "apps.email_center", "apps.whatsapp", "apps.intelligence", "apps.thor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True, "OPTIONS": {}}]

# ── Database (Supabase PostgreSQL) ──
# Runtime connections assume the role `app_backend` (subject to RLS); migrations run with
# DB_ROLE empty (owner). Django's own tables live in the `django` schema, never exposed by the Data API.
_db_role = env("DB_ROLE", "app_backend")
_options = "-c search_path=django,public"
if _db_role:
    _options += f" -c role={_db_role}"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "NAME": env("DB_NAME", "postgres"),
        "USER": env("DB_USER", "postgres"),
        "PASSWORD": env("DB_PASSWORD"),
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        "ATOMIC_REQUESTS": True,  # business change + audit event in the same transaction
        "OPTIONS": {"options": _options, "sslmode": env("DB_SSLMODE", "require")},
        "TEST": {"NAME": env("DB_TEST_NAME", "growth_test")},
    }
}
# Separate autocommit connection for out-of-band technical records (execution logs, error events)
DATABASES["logs"] = {**DATABASES["default"], "ATOMIC_REQUESTS": False, "TEST": {"MIRROR": "default"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Supabase ──
SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SUPABASE_PROJECT_REF = env("SUPABASE_PROJECT_REF")
SUPABASE_ANON_KEY = env("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")  # backend only, never sent to the browser
SUPABASE_JWT_SECRET = env("SUPABASE_JWT_SECRET")  # legacy HS256 projects; JWKS used otherwise
SUPABASE_JWT_AUDIENCE = env("SUPABASE_JWT_AUDIENCE", "authenticated")
SUPABASE_STORAGE_BUCKET = env("SUPABASE_STORAGE_BUCKET", "tenant-files")

# ── REST ──
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.SupabaseJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend",
                                "rest_framework.filters.SearchFilter", "rest_framework.filters.OrderingFilter"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle", "rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": env("THROTTLE_USER", "600/min"), "anon": env("THROTTLE_ANON", "30/min")},
    "UNAUTHENTICATED_USER": None,
}
SPECTACULAR_SETTINGS = {"TITLE": "Growth IA API", "VERSION": APP_VERSION, "SERVE_INCLUDE_SCHEMA": False,
                        "SCHEMA_PATH_PREFIX": "/api/v1"}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_HEADERS = ["authorization", "content-type", "x-tenant-id", "x-request-id", "x-correlation-id",
                      "accept-language", "if-match"]
CORS_EXPOSE_HEADERS = ["x-request-id", "x-correlation-id"]

# ── Redis / Celery ──
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL,
                      "KEY_PREFIX": "growth"}}
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = None  # business state is persisted in PostgreSQL (execution_logs), never only in Redis
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_TIME_LIMIT = 900
CELERY_TASK_SOFT_TIME_LIMIT = 840
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE = "UTC"

# ── Security ──
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECRETS_ENCRYPTION_KEY = env("SECRETS_ENCRYPTION_KEY")  # Fernet key for local secret encryption fallback

# ── I18N ──
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── Logging (structured JSON with request/correlation ids) ──
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"context": {"()": "apps.core.logging.ContextFilter"}},
    "formatters": {"json": {"()": "pythonjsonlogger.json.JsonFormatter",
                            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(correlation_id)s %(tenant_id)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "filters": ["context"]}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

GROWTH = {
    "DEMO_TENANT_LIMIT_PER_USER": 1,
    "INVITATION_TTL_HOURS": int(env("INVITATION_TTL_HOURS", "168")),
    "EXPORT_LINK_TTL_SECONDS": int(env("EXPORT_LINK_TTL_SECONDS", "900")),
    "PILOT_REQUIRE_MFA": env_bool("PILOT_REQUIRE_MFA", True),
    "FRONTEND_URL": env("FRONTEND_URL", "http://localhost:5173"),
}

# ── E-mail (notifications) ──
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Growth IA <no-reply@example.com>")

# ── PROMPT 2 ──
PUBLIC_API_URL = env("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")  # OAuth callbacks & webhooks
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_IDS = {k: env(f"STRIPE_PRICE_{k}") for k in ("STARTER", "GROWTH", "GROWTH_ENTREPRISE")}
CRAWLER_USER_AGENT = env("CRAWLER_USER_AGENT", "GrowthIA-Bot/1.0 (+https://growth-ia.example/bot)")
CRAWLER_MAX_PAGES = int(env("CRAWLER_MAX_PAGES", "200"))
CRAWLER_DELAY_SECONDS = float(env("CRAWLER_DELAY_SECONDS", "0.5"))
ATTACHMENT_MAX_BYTES = int(env("ATTACHMENT_MAX_BYTES", str(20 * 1024 * 1024)))
ATTACHMENT_ALLOWED_MIME = env_list("ATTACHMENT_ALLOWED_MIME", "application/pdf,image/png,image/jpeg,image/gif,text/plain,text/csv,"
                                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
                                   "application/vnd.openxmlformats-officedocument.presentationml.presentation")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
