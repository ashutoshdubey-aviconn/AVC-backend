import os

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "mqtt_debug.sqlite3"),
    }
}
DATABASE_ROUTERS = []
