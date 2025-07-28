from django.contrib import admin
from django.utils.html import format_html
from .models import (
    SalesOrder, SalesOrderLineItem, GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem, StoreAuthorization
)


class SalesOrderLineItemInline(admin.TabularInline):
    model = SalesOrderLineItem
    readonly_fields = ['object_id', 'product_id', 'product_name', 'quantity', 'unit_price', 'unit_of_measurement']
    extra = 0
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = ['sales_order_id', 'source_store', 'destination_store', 'total_net_amount', 'order_date', 'delivery_status_display']
    list_filter = ['order_date', 'source_store', 'destination_store', 'delivery_status_code']
    search_fields = ['sales_order_id', 'object_id']
    readonly_fields = ['object_id', 'sales_order_id', 'total_net_amount', 'order_date', 'metadata']
    inlines = [SalesOrderLineItemInline]
    
    def delivery_status_display(self, obj):
        status_colors = {
            '1': 'red',
            '2': 'orange', 
            '3': 'green'
        }
        color = status_colors.get(obj.delivery_status[0], 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.delivery_status[1]
        )
    delivery_status_display.short_description = 'Delivery Status'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SalesOrderLineItem)
class SalesOrderLineItemAdmin(admin.ModelAdmin):
    list_display = ['sales_order', 'product_name', 'quantity', 'unit_price', 'issued_quantity', 'received_quantity']
    list_filter = ['sales_order__source_store', 'sales_order__destination_store']
    search_fields = ['product_name', 'product_id', 'sales_order__sales_order_id']
    readonly_fields = ['object_id', 'product_id', 'product_name', 'quantity', 'unit_price', 'unit_of_measurement', 'metadata']
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


class GoodsIssueLineItemInline(admin.TabularInline):
    model = GoodsIssueLineItem
    readonly_fields = ['sales_order_line_item', 'quantity_issued', 'issued_value']
    extra = 0


@admin.register(GoodsIssueNote)
class GoodsIssueNoteAdmin(admin.ModelAdmin):
    list_display = ['issue_number', 'sales_order', 'source_store', 'created_date', 'created_by', 'total_issued_value', 'posted_to_icg', 'posted_to_sap']
    list_filter = ['created_date', 'source_store', 'posted_to_icg', 'posted_to_sap']
    search_fields = ['issue_number', 'sales_order__sales_order_id']
    readonly_fields = ['issue_number', 'sales_order', 'source_store', 'created_date', 'created_by', 'total_issued_value']
    inlines = [GoodsIssueLineItemInline]
    
    def has_add_permission(self, request):
        return False


@admin.register(GoodsIssueLineItem)
class GoodsIssueLineItemAdmin(admin.ModelAdmin):
    list_display = ['goods_issue', 'get_product_name', 'quantity_issued', 'issued_value', 'received_quantity']
    list_filter = ['goods_issue__created_date', 'goods_issue__source_store']
    search_fields = ['sales_order_line_item__product_name', 'goods_issue__issue_number']
    readonly_fields = ['goods_issue', 'sales_order_line_item', 'quantity_issued', 'issued_value', 'received_quantity']
    
    def get_product_name(self, obj):
        return obj.sales_order_line_item.product_name
    get_product_name.short_description = 'Product Name'
    
    def has_add_permission(self, request):
        return False


class TransferReceiptLineItemInline(admin.TabularInline):
    model = TransferReceiptLineItem
    readonly_fields = ['goods_issue_line_item', 'quantity_received', 'received_value']
    extra = 0


@admin.register(TransferReceiptNote)
class TransferReceiptNoteAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'get_sales_order', 'destination_store', 'created_date', 'created_by', 'total_received_value', 'posted_to_icg']
    list_filter = ['created_date', 'destination_store', 'posted_to_icg']
    search_fields = ['receipt_number', 'goods_issue__sales_order__sales_order_id']
    readonly_fields = ['receipt_number', 'goods_issue', 'destination_store', 'created_date', 'created_by', 'total_received_value']
    inlines = [TransferReceiptLineItemInline]
    
    def get_sales_order(self, obj):
        return obj.goods_issue.sales_order
    get_sales_order.short_description = 'Sales Order'
    
    def has_add_permission(self, request):
        return False


@admin.register(TransferReceiptLineItem)
class TransferReceiptLineItemAdmin(admin.ModelAdmin):
    list_display = ['transfer_receipt', 'get_product_name', 'quantity_received', 'received_value']
    list_filter = ['transfer_receipt__created_date', 'transfer_receipt__destination_store']
    search_fields = ['goods_issue_line_item__sales_order_line_item__product_name', 'transfer_receipt__receipt_number']
    readonly_fields = ['transfer_receipt', 'goods_issue_line_item', 'quantity_received', 'received_value']
    
    def get_product_name(self, obj):
        return obj.goods_issue_line_item.sales_order_line_item.product_name
    get_product_name.short_description = 'Product Name'
    
    def has_add_permission(self, request):
        return False


@admin.register(StoreAuthorization)
class StoreAuthorizationAdmin(admin.ModelAdmin):
    list_display = ['user', 'store', 'role', 'created_date']
    list_filter = ['role', 'store', 'created_date']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'store__store_name']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'store')