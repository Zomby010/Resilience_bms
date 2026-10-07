from django.apps import AppConfig


class TrackingConfig(AppConfig):
    name = "tracking"
    verbose_name = "GPS tracking"

    def ready(self):
        from . import signals  # noqa: F401
