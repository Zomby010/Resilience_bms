from django.apps import AppConfig


class OperationsConfig(AppConfig):
    name = "operations"
    verbose_name = "Site operations"

    def ready(self):
        from . import signals  # noqa: F401
