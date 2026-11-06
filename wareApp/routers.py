class SecondaryDBRouter:
    """
    Routes reads/writes for specific models to the secondary database.
    """
    secondary_app_labels = {"HourlyLoadData", "RawLoadData",'DailyLoadData', 'MainsDgLoadData'}  # or use specific model names

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.secondary_app_labels:
            return 'secondary'
        return None  # falls back to default

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.secondary_app_labels:
            return 'secondary'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # Allow relations if both models are in the same db
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.secondary_app_labels:
            return False  # ← prevents migrations on secondary DB
        return None
