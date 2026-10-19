"""Django settings for the warehouse project.

Every secret and every per-server value comes from ``warehouse/.env`` (python-decouple).
``ENV`` selects the profile:

* ``PROD``  - servers (main and test). ``SECRET_KEY`` is required.
* ``Local`` - developer machine with PostgreSQL.
* anything else (``CI``) - SQLite, used by the test suite.
"""

import os

from decouple import config
from kombu import Queue

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

env = config("ENV", default="Local")
IS_PROD = env == "PROD"


def _host_list(value):
    """Accept ``a,b`` as well as the ``["a", "b"]`` form used in the server .env files."""
    return [item.strip().strip("'\"") for item in value.strip("[] ").split(",") if item.strip()]


# --- Security -----------------------------------------------------------------

if IS_PROD:
    SECRET_KEY = config("SECRET_KEY")
else:
    SECRET_KEY = config("SECRET_KEY", default="django-insecure-local-development-only")

DEBUG = config("DEBUG", default=not IS_PROD, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*", cast=_host_list)
CORS_ORIGIN_ALLOW_ALL = config("CORS_ORIGIN_ALLOW_ALL", default=True, cast=bool)

# The servers are reached over plain HTTP (gunicorn :8000 / nginx), so these
# stay off unless the server's .env turns them on.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=False, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=False, cast=bool)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --- Application ----------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "wareApp",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_extensions",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # CORS middleware early
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "warehouse.urls"
WSGI_APPLICATION = "warehouse.wsgi.application"
SETTINGS_PATH = os.path.normpath(os.path.dirname(__file__))

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "5/minute", "user": "1000/minute"},
}

# --- Database -------------------------------------------------------------------

USE_SECONDARY_DATABASE = config("USE_SECONDARY_DATABASE", default=False, cast=bool)
DATABASE_ROUTERS = (
    ["wareApp.routers.SecondaryDBRouter"] if USE_SECONDARY_DATABASE else []
)

if env in {"Local", "PROD"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_HOSTNAME"),
            "USER": config("DB_USERNAME"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST"),
            "PORT": config("DB_PORT"),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        },
    }
    # Set only in the MQTT processing units (deploy/systemd/), not in .env:
    # DB_SYNCHRONOUS_COMMIT=off lets their commits return before the WAL is
    # flushed to disk. A PostgreSQL crash can lose the last fraction of a
    # second of commits (no corruption); missed hours are re-requested by the
    # recovery mechanism. The web app keeps the default (on).
    DB_SYNCHRONOUS_COMMIT = config("DB_SYNCHRONOUS_COMMIT", default="")
    if DB_SYNCHRONOUS_COMMIT:
        DATABASES["default"]["OPTIONS"] = {
            "options": f"-c synchronous_commit={DB_SYNCHRONOUS_COMMIT}"
        }
    # Main-server database, read by roadcast_monthly_refuel_report.py on the
    # test server. Only configured when its password is in the environment.
    MAIN_DB_PASSWORD = config("MAIN_DB_PASSWORD", default="")
    if MAIN_DB_PASSWORD:
        DATABASES["main"] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("MAIN_DB_NAME", default="warehouse"),
            "USER": config("MAIN_DB_USER", default="aviconn"),
            "PASSWORD": MAIN_DB_PASSWORD,
            "HOST": config("MAIN_DB_HOST", default="172.31.9.28"),
            "PORT": config("MAIN_DB_PORT", default="5432"),
        }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "wareApp.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization and static files -----------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = False

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static/")

# --- Email ----------------------------------------------------------------------

EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=25, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="")
# Never let a slow SMTP server block an MQTT processing worker indefinitely.
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=10, cast=int)
# Alarm emails (wareApp/sendmail.py). OVERRIDE_TO (comma list) replaces the
# recipients of every alarm email. While the alarm emails are being tested it
# defaults to the tester's office address on every server; set
# ALARM_EMAIL_OVERRIDE_TO= (empty) in .env to send to the real recipients.
# DEFAULT_TO receives the alarm types that have no recipient of their own
# (consumption, meter, PF, DG) once the override is off.
ALARM_EMAIL_OVERRIDE_TO = config(
    "ALARM_EMAIL_OVERRIDE_TO", default="ashutosh.dubey@aviconncorp.com", cast=_host_list
)
ALARM_EMAIL_DEFAULT_TO = config("ALARM_EMAIL_DEFAULT_TO", default="", cast=_host_list)
# Alarm lists (wareApp/alarm_feed.py): only issues seen within this many days
# are shown; 0 shows every active issue.
ALARM_FEED_MAX_AGE_DAYS = config("ALARM_FEED_MAX_AGE_DAYS", default=30, cast=int)
# Consumption alarms (wareApp/mqtt/services/consumption_alarms.py).
ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT = config(
    "ALARM_HIGH_CONSUMPTION_DEFAULT_PERCENT", default=75, cast=float
)
ALARM_ACTIVITY_THRESHOLD_KWH = config("ALARM_ACTIVITY_THRESHOLD_KWH", default=0.01, cast=float)
# After recovery, re-evaluate alarms only for days within this many days.
ALARM_REEVALUATE_DAYS = config("ALARM_REEVALUATE_DAYS", default=7, cast=int)

# --- DG fuel providers -----------------------------------------------------------

# Roadcast pull API (wareApp/fuel_providers.py); the pull is skipped when unset.
ROADCAST_PULL_USERNAME = config("ROADCAST_PULL_USERNAME", default="")
ROADCAST_PULL_PASSWORD = config("ROADCAST_PULL_PASSWORD", default="")

# --- Cache ----------------------------------------------------------------------

REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "KEY_PREFIX": "avc",
        }
    }
else:
    # Per-process cache. Cooldowns and config caching still work with the
    # site-partitioned workers (a site always lands on the same worker), but a
    # shared Redis cache is recommended on servers. The default limit of 300
    # keys is far too small: one duplicate-check key per consumption packet and
    # one cooldown key per gap made it evict live cooldowns (repeated recovery
    # requests on the test server).
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "OPTIONS": {
                "MAX_ENTRIES": config("LOCMEM_CACHE_MAX_ENTRIES", default=200_000, cast=int)
            },
        }
    }

# --- Celery ---------------------------------------------------------------------

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="amqp://guest@localhost//")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="rpc://")
CELERY_TIMEZONE = TIME_ZONE
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# The MQTT pipeline is fire-and-forget: nothing reads task results, so do not
# publish a result message for every processed packet.
CELERY_TASK_IGNORE_RESULT = True
# apply_async returns only after RabbitMQ has confirmed the message.
CELERY_BROKER_TRANSPORT_OPTIONS = {"confirm_publish": True}

# --- MQTT pipeline --------------------------------------------------------------

# MQTT_SITE_PARTITIONS = 0 keeps the single serial ``queue1_processing`` queue.
# MQTT_SITE_PARTITIONS = N routes queue-1 messages to ``mqtt.site.0`` ..
# ``mqtt.site.N-1`` by ``site_id % N``; run one worker (concurrency 1) per
# partition so every site stays strictly ordered while sites run in parallel.
MQTT_SITE_PARTITIONS = config("MQTT_SITE_PARTITIONS", default=0, cast=int)
MQTT_BROKER_HOST = config("MQTT_BROKER_HOST", default="127.0.0.1")
MQTT_BROKER_PORT = config("MQTT_BROKER_PORT", default=1883, cast=int)
# Stable, unique client IDs: the persistent broker session is keyed on them.
MQTT_QUEUE1_CLIENT_ID = config("MQTT_QUEUE1_CLIENT_ID", default="server_paho_client_1")
MQTT_QUEUE2_CLIENT_ID = config("MQTT_QUEUE2_CLIENT_ID", default="server_paho_client_2")
# Consumption packets already processed are skipped for this long (0 = off).
MQTT_IDEMPOTENCY_TTL_SECONDS = config(
    "MQTT_IDEMPOTENCY_TTL_SECONDS", default=6 * 60 * 60, cast=int
)
# One recovery request per (site, aisle or power source) per cooldown window.
MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS = config(
    "MQTT_RECOVERY_REQUEST_COOLDOWN_SECONDS", default=600, cast=int
)
# Recovery status (see wareApp/mqtt/services/recovery_status.py).
# A request that gets no complete answer is retried after each cooldown; after
# MQTT_RECOVERY_MAX_ATTEMPTS it is marked failed, and a new gap packet may start
# a fresh request once MQTT_RECOVERY_FAILED_RETRY_SECONDS have passed.
MQTT_RECOVERY_MAX_ATTEMPTS = config("MQTT_RECOVERY_MAX_ATTEMPTS", default=3, cast=int)
MQTT_RECOVERY_FAILED_RETRY_SECONDS = config(
    "MQTT_RECOVERY_FAILED_RETRY_SECONDS", default=6 * 60 * 60, cast=int
)
# recovery_status_sweep: aisle with no consumption for this long -> late / missing.
MQTT_SYNC_LATE_SECONDS = config("MQTT_SYNC_LATE_SECONDS", default=70 * 60, cast=int)
MQTT_SYNC_MISSING_SECONDS = config(
    "MQTT_SYNC_MISSING_SECONDS", default=130 * 60, cast=int
)
# Publish MQTT packet tasks as non-persistent RabbitMQ messages (no disk write
# per packet); see wareApp/mqtt/consumers.py. Set False to persist them.
MQTT_TRANSIENT_MESSAGES = config("MQTT_TRANSIENT_MESSAGES", default=True, cast=bool)
# Send alarm emails through the ``notifications`` queue after commit instead
# of inline in the MQTT processing worker.
MQTT_ASYNC_NOTIFICATIONS = config("MQTT_ASYNC_NOTIFICATIONS", default=True, cast=bool)

CELERY_TASK_QUEUES = (
    Queue("celery"),
    Queue("queue1"),
    Queue("queue2"),
    Queue("queue1_processing"),
    Queue("queue2_processing"),
    Queue("notifications"),
    *(Queue(f"mqtt.site.{index}") for index in range(MQTT_SITE_PARTITIONS)),
)

# --- Logging --------------------------------------------------------------------

LOG_FILE = f"{BASE_DIR}/logges"
# File handlers fail at start-up when their folder is missing (fresh checkout).
os.makedirs(f"{LOG_FILE}/recovery", exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime}|{levelname}|{module}|{process:d}--{thread:d}|{message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": f"{LOG_FILE}/debug.log",
            "formatter": "verbose",
        },
        "recovery_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": f"{LOG_FILE}/recovery/recovery.log",
            "formatter": "verbose",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
        },
        "dg_fuel_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": f"{LOG_FILE}/dg_fuel.log",
            "formatter": "verbose",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 10,
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "propagate": True,
        },
        "django.request": {
            "handlers": ["file", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "wareApp.recovery": {
            "handlers": ["recovery_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "wareApp.dg_fuel": {
            "handlers": ["dg_fuel_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "wareApp.fuel_providers": {
            "handlers": ["dg_fuel_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "wareApp.dg_fuel.ingestion": {
            "handlers": ["dg_fuel_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "wareApp.dg_fuel.sessions": {
            "handlers": ["dg_fuel_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "fetch_fuel_data": {
            "handlers": ["dg_fuel_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
