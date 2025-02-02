from django.apps import AppConfig


class InvoiceServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'invoice_service'
    verbose_name = '3. Vendor Invoicing'