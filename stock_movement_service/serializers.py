from datetime import datetime
from rest_framework import serializers
from django.forms.models import model_to_dict
from egrn_service.serializers import StoreSerializer
from .models import (
    SalesOrder, SalesOrderLineItem, GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem, StoreAuthorization
)


class SalesOrderLineItemSerializer(serializers.ModelSerializer):
    """Serializer for Sales Order Line Items"""
    
    # Related fields
    goods_issue_items = serializers.SerializerMethodField()
    
    # Computed fields
    delivery_status_code = serializers.SerializerMethodField()
    delivery_status_text = serializers.SerializerMethodField()
    delivery_outstanding_quantity = serializers.SerializerMethodField()
    delivery_completed = serializers.SerializerMethodField()
    issued_quantity = serializers.FloatField(read_only=True)
    received_quantity = serializers.FloatField(read_only=True)
    
    def get_goods_issue_items(self, obj):
        """Get related goods issue items"""
        from .serializers import GoodsIssueLineItemSerializer
        return GoodsIssueLineItemSerializer(obj.goods_issue_items.all(), many=True).data
    
    def get_delivery_outstanding_quantity(self, obj):
        """Calculate outstanding quantity"""
        return float(obj.quantity) - float(obj.issued_quantity)
    
    def get_delivery_status_code(self, obj):
        """Get delivery status code"""
        return obj.delivery_status[0]
    
    def get_delivery_status_text(self, obj):
        """Get delivery status text"""
        return obj.delivery_status[1]
    
    def get_delivery_completed(self, obj):
        """Check if delivery is completed"""
        return self.get_delivery_outstanding_quantity(obj) == 0
    
    class Meta:
        model = SalesOrderLineItem
        fields = [
            'object_id', 'product_id', 'product_name', 'quantity', 'unit_price', 
            'unit_of_measurement', 'delivery_status_code', 'delivery_status_text',
            'issued_quantity', 'received_quantity', 'delivery_outstanding_quantity',
            'delivery_completed', 'metadata', 'goods_issue_items'
        ]


class SalesOrderSerializer(serializers.ModelSerializer):
    """Serializer for Sales Orders"""
    
    # Related fields
    line_items = SalesOrderLineItemSerializer(many=True, read_only=True)
    source_store = StoreSerializer(read_only=True)
    destination_store = StoreSerializer(read_only=True)
    
    # Computed fields
    delivery_status_code = serializers.SerializerMethodField()
    delivery_status_text = serializers.SerializerMethodField()
    delivery_completed = serializers.SerializerMethodField()
    
    def get_delivery_status_code(self, obj):
        """Get delivery status code"""
        return obj.delivery_status[0]
    
    def get_delivery_status_text(self, obj):
        """Get delivery status text"""
        return obj.delivery_status[1]
    
    def get_delivery_completed(self, obj):
        """Check if delivery is completed"""
        return obj.delivery_status[0] == '3'
    
    def to_representation(self, instance):
        """Convert datetime to date if needed"""
        if isinstance(instance.order_date, datetime):
            instance.order_date = instance.order_date.date()
        return super().to_representation(instance)
    
    class Meta:
        model = SalesOrder
        fields = [
            'object_id', 'sales_order_id', 'source_store', 'destination_store',
            'total_net_amount', 'order_date', 'delivery_status_code',
            'delivery_status_text', 'delivery_completed', 'line_items', 'metadata'
        ]


class GoodsIssueLineItemSerializer(serializers.ModelSerializer):
    """Serializer for Goods Issue Line Items"""
    
    # Related fields
    sales_order_line_item = SalesOrderLineItemSerializer(read_only=True)
    receipt_items = serializers.SerializerMethodField()
    
    # Computed fields
    issued_value = serializers.FloatField(read_only=True)
    received_quantity = serializers.FloatField(read_only=True)
    
    def get_receipt_items(self, obj):
        """Get related transfer receipt items"""
        from .serializers import TransferReceiptLineItemSerializer
        return TransferReceiptLineItemSerializer(obj.receipt_items.all(), many=True).data
    
    class Meta:
        model = GoodsIssueLineItem
        fields = [
            'id', 'sales_order_line_item', 'quantity_issued', 'issued_value',
            'received_quantity', 'metadata', 'receipt_items'
        ]


class GoodsIssueNoteSerializer(serializers.ModelSerializer):
    """Serializer for Goods Issue Notes"""
    
    # Related fields
    sales_order = SalesOrderSerializer(read_only=True)
    source_store = StoreSerializer(read_only=True)
    line_items = GoodsIssueLineItemSerializer(many=True, read_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    
    # Computed fields
    total_issued_value = serializers.FloatField(read_only=True)
    
    class Meta:
        model = GoodsIssueNote
        fields = [
            'issue_number', 'sales_order', 'source_store', 'created_date',
            'created_by', 'total_issued_value', 'posted_to_icg', 'posted_to_sap',
            'line_items', 'metadata'
        ]


class TransferReceiptLineItemSerializer(serializers.ModelSerializer):
    """Serializer for Transfer Receipt Line Items"""
    
    # Related fields
    goods_issue_line_item = GoodsIssueLineItemSerializer(read_only=True)
    
    # Computed fields
    received_value = serializers.FloatField(read_only=True)
    
    class Meta:
        model = TransferReceiptLineItem
        fields = [
            'id', 'goods_issue_line_item', 'quantity_received', 'received_value', 'metadata'
        ]


class TransferReceiptNoteSerializer(serializers.ModelSerializer):
    """Serializer for Transfer Receipt Notes"""
    
    # Related fields
    goods_issue = GoodsIssueNoteSerializer(read_only=True)
    destination_store = StoreSerializer(read_only=True)
    line_items = TransferReceiptLineItemSerializer(many=True, read_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    
    # Computed fields
    total_received_value = serializers.FloatField(read_only=True)
    
    class Meta:
        model = TransferReceiptNote
        fields = [
            'receipt_number', 'goods_issue', 'destination_store', 'created_date',
            'created_by', 'total_received_value', 'posted_to_icg',
            'line_items', 'metadata'
        ]


class StoreAuthorizationSerializer(serializers.ModelSerializer):
    """Serializer for Store Authorization"""
    
    # Related fields
    user = serializers.StringRelatedField(read_only=True)
    store = StoreSerializer(read_only=True)
    
    class Meta:
        model = StoreAuthorization
        fields = [
            'id', 'user', 'store', 'role', 'created_date', 'metadata'
        ]


# Input serializers for creating records
class CreateGoodsIssueSerializer(serializers.Serializer):
    """Serializer for creating goods issue notes"""
    
    sales_order_id = serializers.IntegerField()
    issued_goods = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField()
        )
    )
    
    def validate_sales_order_id(self, value):
        """Validate sales order exists"""
        try:
            SalesOrder.objects.get(sales_order_id=value)
            return value
        except SalesOrder.DoesNotExist:
            raise serializers.ValidationError("Sales order not found.")


class CreateTransferReceiptSerializer(serializers.Serializer):
    """Serializer for creating transfer receipt notes"""
    
    goods_issue_number = serializers.IntegerField()
    received_goods = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField()
        )
    )
    
    def validate_goods_issue_number(self, value):
        """Validate goods issue exists"""
        try:
            GoodsIssueNote.objects.get(issue_number=value)
            return value
        except GoodsIssueNote.DoesNotExist:
            raise serializers.ValidationError("Goods issue note not found.")


class StoreTransferSummarySerializer(serializers.Serializer):
    """Serializer for store transfer summary data"""
    
    store = StoreSerializer(read_only=True)
    total_outbound_orders = serializers.IntegerField(read_only=True)
    total_inbound_orders = serializers.IntegerField(read_only=True)
    pending_issues = serializers.IntegerField(read_only=True)
    pending_receipts = serializers.IntegerField(read_only=True)
    total_value_issued = serializers.DecimalField(max_digits=15, decimal_places=3, read_only=True)
    total_value_received = serializers.DecimalField(max_digits=15, decimal_places=3, read_only=True)