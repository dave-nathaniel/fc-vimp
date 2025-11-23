from django.apps import AppConfig


class CoreServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core_service'
    verbose_name = '4. Core Service'
    
    def ready(self):
        # Import signal handlers to register them
        import core_service.signals
