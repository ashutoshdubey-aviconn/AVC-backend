from django.apps import AppConfig


class WareappConfig(AppConfig):
    """Django app config for wareApp.

    Origin: Ashu (changed from main)
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "wareApp"

    def ready(self):
        # Register cache-invalidation signal receivers in every process
        # (web and workers) so admin edits drop cached site configuration.
        """Runs at Django start-up: imports alarm_policy and site_cache so their signal handlers (cache
        refresh on save) are connected.

        Origin: Ashu
        """
        from wareApp.mqtt.services import alarm_policy  # noqa: F401
        from wareApp.mqtt.services import site_cache  # noqa: F401
