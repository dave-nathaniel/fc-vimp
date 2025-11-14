from django.apps import AppConfig


class AppSettingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_settings'
    verbose_name = '1. App Configuration'

    # B2 implementation – ensure custom content types & permissions are created
    def ready(self):
        """Hook into post_migrate so DB tables are guaranteed to exist."""
        from django.db.models.signals import post_migrate
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth.models import Permission

        from . import models  # Local import to avoid side-effects at import time

        def create_custom_permissions(sender, **kwargs):
            app_label = self.label

            # Proxy models that need their own app label
            proxy_models = [
                models.StoreProxy,
                models.SurchargeProxy,
                models.ConversionProxy,
                models.ProductConfigurationProxy,
            ]

            default_perms = ["add", "change", "delete", "view"]

            for mdl in proxy_models:
                ct, _ = ContentType.objects.get_or_create(
                    model=mdl._meta.model_name,
                    app_label=app_label,
                )

                for perm in default_perms:
                    Permission.objects.get_or_create(
                        codename=f"{perm}_{mdl._meta.model_name}",
                        content_type=ct,
                        defaults={"name": f"Can {perm} {mdl._meta.verbose_name}"},
                    )

        # Connect only once per process
        post_migrate.connect(create_custom_permissions, sender=self)