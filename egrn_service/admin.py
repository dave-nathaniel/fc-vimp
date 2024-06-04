from django.contrib import admin
from .forms import ConversionForm
from .models import Store, PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedNote, GoodsReceivedLineItem, Conversion, ProductConversion

class ConversionAdmin(admin.ModelAdmin):
    form = ConversionForm

admin.site.register(Store)
admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderLineItem)
admin.site.register(GoodsReceivedNote)
admin.site.register(GoodsReceivedLineItem)
admin.site.register(ProductConversion)
admin.site.register(Conversion, ConversionAdmin)