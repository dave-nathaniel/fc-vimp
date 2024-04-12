from django.contrib import admin
from .models import Surcharge, Invoice, InvoiceLineItem

admin.site.register(Surcharge)
admin.site.register(Invoice)
admin.site.register(InvoiceLineItem)