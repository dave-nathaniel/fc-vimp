from django.contrib import admin
from .forms import ConversionForm
from .models import Store, PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedNote, GoodsReceivedLineItem, Conversion, ProductConfiguration, Surcharge
from django.db.models.fields.json import JSONField
from jsoneditor.forms import JSONEditor

class ConversionAdmin(admin.ModelAdmin):
	form = ConversionForm
	search_fields = ['name', 'conversion_field', 'conversion_method']
	formfield_overrides = {
		JSONField: {'widget': JSONEditor},
	}

class ProductConfigurationAdmin(admin.ModelAdmin):
	search_fields = ['product_id', 'conversion__name', 'metadata']
	formfield_overrides = {
		JSONField: {'widget': JSONEditor},
	}

admin.site.register(Store)
admin.site.register(Surcharge)
admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderLineItem)
admin.site.register(GoodsReceivedNote)
admin.site.register(GoodsReceivedLineItem)
admin.site.register(ProductConfiguration, ProductConfigurationAdmin)
admin.site.register(Conversion, ConversionAdmin)