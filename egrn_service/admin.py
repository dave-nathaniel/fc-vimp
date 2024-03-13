from django.contrib import admin
from .models import Store, PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedNote, GoodsReceivedLineItem

admin.site.register(Store)
admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderLineItem)
admin.site.register(GoodsReceivedNote)
admin.site.register(GoodsReceivedLineItem)
