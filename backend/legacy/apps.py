from django.apps import AppConfig


class LegacyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'legacy'

    def ready(self):
        # 2026-11-17: keep the settled legacy history warm in every web worker (see legacy/warm.py).
        from . import warm
        warm.start()
