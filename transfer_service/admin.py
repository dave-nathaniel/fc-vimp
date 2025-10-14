from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import (
    InboundDelivery, InboundDeliveryLineItem,
    TransferReceiptNote, TransferReceiptLineItem,
    StoreAuthorization
)


class TransferReceiptLineItemInline(admin.TabularInline):
    model = TransferReceiptLineItem
    extra = 0


@admin.register(TransferReceiptNote)
class TransferReceiptNoteAdmin(ModelAdmin):
    list_display = ('receipt_number', 'inbound_delivery', 'created_date', 'created_by', 'posted_to_icg')
    list_filter = ('posted_to_icg', 'created_date', 'inbound_delivery__destination_store')
    search_fields = ('receipt_number', 'inbound_delivery__delivery_id')
    readonly_fields = ('receipt_number', 'created_date')
    inlines = [TransferReceiptLineItemInline]


class InboundDeliveryLineItemInline(admin.TabularInline):
    model = InboundDeliveryLineItem
    extra = 0
    readonly_fields = ('object_id', 'product_id', 'product_name', 'quantity_expected', 'quantity_received', 'unit_of_measurement')


@admin.register(InboundDelivery)
class InboundDeliveryAdmin(ModelAdmin):
    list_display = ('delivery_id', 'source_location_name', 'destination_store', 'delivery_date', 'delivery_status_code', 'delivery_type_code', 'is_fully_received')
    list_filter = ('delivery_status_code', 'delivery_type_code', 'delivery_date', 'destination_store', 'source_location_id')
    search_fields = ('delivery_id', 'object_id', 'sales_order_reference', 'source_location_id', 'source_location_name')
    readonly_fields = ('object_id', 'delivery_id', 'delivery_date', 'created_date', 'total_quantity_expected', 'total_quantity_received')
    inlines = [InboundDeliveryLineItemInline]


@admin.register(StoreAuthorization)
class StoreAuthorizationAdmin(ModelAdmin):
    list_display = ('user', 'store', 'role', 'created_date')
    list_filter = ('role', 'created_date', 'store')
    search_fields = ('user__username', 'user__email', 'store__store_name')
    readonly_fields = ('created_date',)