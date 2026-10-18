from django.apps import AppConfig


class WareappConfig(AppConfig):
    defualt_auto_field = 'django.db.models.BigAutoField'
    name = 'wareApp'

    def ready(self):
        # Register cache-invalidation signal receivers in every process
        # (web and workers) so admin edits drop cached site configuration.
        from wareApp.mqtt.services import site_cache  # noqa: F401
