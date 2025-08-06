from django.contrib import admin
from .models import (
    SalesOrder, SalesOrderLineItem,
    GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem,
    InboundDelivery, InboundDeliveryLineItem,
    StoreAuthorization
)


class SalesOrderLineItemInline(admin.TabularInline):
    model = SalesOrderLineItem
    extra = 0
    readonly_fields = ('object_id', 'product_id', 'product_name', 'quantity', 'unit_price', 'unit_of_measurement')


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = ('sales_order_id', 'source_store', 'destination_store', 'total_net_amount', 'order_date', 'delivery_status_code')
    list_filter = ('delivery_status_code', 'order_date', 'source_store', 'destination_store')
    search_fields = ('sales_order_id', 'object_id')
    readonly_fields = ('object_id', 'sales_order_id', 'total_net_amount', 'order_date', 'created_date')
    inlines = [SalesOrderLineItemInline]


class GoodsIssueLineItemInline(admin.TabularInline):
    model = GoodsIssueLineItem
    extra = 0


@admin.register(GoodsIssueNote)
class GoodsIssueNoteAdmin(admin.ModelAdmin):
    list_display = ('issue_number', 'sales_order', 'source_store', 'created_date', 'created_by', 'posted_to_icg', 'posted_to_sap')
    list_filter = ('posted_to_icg', 'posted_to_sap', 'created_date', 'source_store')
    search_fields = ('issue_number', 'sales_order__sales_order_id')
    readonly_fields = ('issue_number', 'created_date')
    inlines = [GoodsIssueLineItemInline]


class TransferReceiptLineItemInline(admin.TabularInline):
    model = TransferReceiptLineItem
    extra = 0


@admin.register(TransferReceiptNote)
class TransferReceiptNoteAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'goods_issue', 'destination_store', 'created_date', 'created_by', 'posted_to_icg')
    list_filter = ('posted_to_icg', 'created_date', 'destination_store')
    search_fields = ('receipt_number', 'goods_issue__issue_number')
    readonly_fields = ('receipt_number', 'created_date')
    inlines = [TransferReceiptLineItemInline]


class InboundDeliveryLineItemInline(admin.TabularInline):
    model = InboundDeliveryLineItem
    extra = 0
    readonly_fields = ('object_id', 'product_id', 'product_name', 'quantity_expected', 'quantity_received', 'unit_of_measurement')


@admin.register(InboundDelivery)
class InboundDeliveryAdmin(admin.ModelAdmin):
    list_display = ('delivery_id', 'source_location_name', 'destination_store', 'delivery_date', 'delivery_status_code', 'delivery_type_code', 'is_fully_received')
    list_filter = ('delivery_status_code', 'delivery_type_code', 'delivery_date', 'destination_store', 'source_location_id')
    search_fields = ('delivery_id', 'object_id', 'sales_order_reference', 'source_location_id', 'source_location_name')
    readonly_fields = ('object_id', 'delivery_id', 'delivery_date', 'created_date', 'total_quantity_expected', 'total_quantity_received')
    inlines = [InboundDeliveryLineItemInline]


@admin.register(StoreAuthorization)
class StoreAuthorizationAdmin(admin.ModelAdmin):
    list_display = ('user', 'store', 'role', 'created_date')
    list_filter = ('role', 'created_date', 'store')
    search_fields = ('user__username', 'user__email', 'store__store_name')
    readonly_fields = ('created_date',)