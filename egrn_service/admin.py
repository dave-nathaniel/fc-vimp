from django.contrib import admin
from .forms import ConversionForm
from .models import Store, PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedNote, GoodsReceivedLineItem, Conversion, ProductConversion, Surcharge
from django.db.models.fields.json import JSONField
from jsoneditor.forms import JSONEditor

class ConversionAdmin(admin.ModelAdmin):
    form = ConversionForm
    formfield_overrides = {
        JSONField: {'widget': JSONEditor},
    }

admin.site.register(Store)
admin.site.register(Surcharge)
admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderLineItem)
admin.site.register(GoodsReceivedNote)
admin.site.register(GoodsReceivedLineItem)
admin.site.register(ProductConversion)
admin.site.register(Conversion, ConversionAdmin)