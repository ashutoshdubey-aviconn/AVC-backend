from .settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "mqtt_debug.sqlite3"),
    }
}
DATABASE_ROUTERS = []
