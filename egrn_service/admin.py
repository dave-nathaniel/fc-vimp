from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import PurchaseOrder, PurchaseOrderLineItem, GoodsReceivedNote, GoodsReceivedLineItem

class PurchaseOrderAdmin(ModelAdmin):
	# Search fields: vendor, object_id, po_id
	search_fields = [
		'vendor__user__first_name',
		'vendor__user__email',
		'vendor__byd_internal_id',
		'object_id',
		'po_id',
		'line_items__product_id',
		'line_items__product_name',
		'line_items__delivery_store__store_name',
        'line_items__delivery_store__store_email',
        'line_items__delivery_store__icg_warehouse_name',
        'line_items__delivery_store__icg_warehouse_code',
        'line_items__delivery_store__byd_cost_center_code',
		
	]

class PurchaseOrderLineItemAdmin(ModelAdmin):
	# Search fields: purchase_order, delivery_store, object_id, product_id, product_name
	search_fields = [
		'purchase_order__po_id',
		'purchase_order__vendor__user__first_name',
		'purchase_order__vendor__user__email',
		'purchase_order__vendor__byd_internal_id',
		'delivery_store__store_name',
		'delivery_store__store_email',
		'delivery_store__icg_warehouse_name',
		'delivery_store__icg_warehouse_code',
		'delivery_store__byd_cost_center_code',
		'object_id',
		'product_id',
		'product_name',
	]

class GoodsReceivedNoteAdmin(ModelAdmin):
	# Search fields: grn_number
	search_fields = [
		'grn_number',
		'purchase_order__vendor__user__first_name',
		'purchase_order__vendor__user__email',
		'purchase_order__vendor__byd_internal_id',
		'purchase_order__po_id'
	]

class GoodsReceivedLineItemAdmin(ModelAdmin):
	# Search fields: grn, purchase_order_line_item, object_id, product_id, product_name
	search_fields = [
		'grn__grn_number',
		'purchase_order_line_item__purchase_order__po_id',
		'purchase_order_line_item__delivery_store__store_name',
		'purchase_order_line_item__delivery_store__store_email',
		'purchase_order_line_item__delivery_store__icg_warehouse_name',
		'purchase_order_line_item__delivery_store__icg_warehouse_code',
		'purchase_order_line_item__delivery_store__byd_cost_center_code',
		'purchase_order_line_item__purchase_order__vendor__user__first_name',
		'purchase_order_line_item__purchase_order__vendor__user__email',
		'purchase_order_line_item__purchase_order__vendor__byd_internal_id',
		'purchase_order_line_item__product_name',
		'purchase_order_line_item__object_id',
		'purchase_order_line_item__product_id',
	]

admin.site.register(PurchaseOrder, PurchaseOrderAdmin)
admin.site.register(PurchaseOrderLineItem, PurchaseOrderLineItemAdmin)
admin.site.register(GoodsReceivedNote, GoodsReceivedNoteAdmin)
admin.site.register(GoodsReceivedLineItem, GoodsReceivedLineItemAdmin)