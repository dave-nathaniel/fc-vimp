from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Invoice, InvoiceLineItem

class InvoiceAdmin(ModelAdmin):
	search_fields = [
        'id',
		'external_document_id',
		'description',
		'payment_terms',
		'payment_reason',
        'purchase_order__po_id',
		'purchase_order__object_id',
		'grn__grn_number',
		'purchase_order__vendor__user__email',
		'purchase_order__vendor__user__first_name',
		'purchase_order__vendor__byd_internal_id',
        'invoice_line_items__po_line_item__product_name',
		'invoice_line_items__po_line_item__object_id',
		'invoice_line_items__po_line_item__product_id',
		'invoice_line_items__po_line_item__delivery_store__store_name',
		'invoice_line_items__po_line_item__delivery_store__store_email',
		'invoice_line_items__po_line_item__delivery_store__icg_warehouse_name',
		'invoice_line_items__po_line_item__delivery_store__icg_warehouse_code',
		'invoice_line_items__po_line_item__delivery_store__byd_cost_center_code',
    ]

admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(InvoiceLineItem)