from django.contrib import admin
from .models import Invoice, InvoiceLineItem

admin.site.register(Invoice)
admin.site.register(InvoiceLineItem)