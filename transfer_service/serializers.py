from rest_framework import serializers
from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import (
    SalesOrder, SalesOrderLineItem,
    GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem
)
from .services import AuthorizationService


class SalesOrderLineItemSerializer(serializers.ModelSerializer):
    # Computed fields
    issued_quantity = serializers.ReadOnlyField()
    received_quantity = serializers.ReadOnlyField()
    delivery_status = serializers.ReadOnlyField()
    
    # Value calculations
    line_total = serializers.SerializerMethodField()
    outstanding_quantity = serializers.SerializerMethodField()
    
    class Meta:
        model = SalesOrderLineItem
        fields = [
            'id', 'object_id', 'product_id', 'product_name', 
            'quantity', 'unit_price', 'unit_of_measurement',
            'issued_quantity', 'received_quantity', 'delivery_status',
            'line_total', 'outstanding_quantity', 'metadata'
        ]
    
    def get_line_total(self, obj):
        """Calculate total value for this line item"""
        return float(obj.quantity) * float(obj.unit_price)
    
    def get_outstanding_quantity(self, obj):
        """Calculate remaining quantity to be received"""
        return float(obj.quantity) - float(obj.received_quantity)


class SalesOrderSerializer(serializers.ModelSerializer):
    line_items = SalesOrderLineItemSerializer(many=True, read_only=True)
    
    # Computed fields for delivery status and quantities
    delivery_status = serializers.ReadOnlyField()
    issued_quantity = serializers.ReadOnlyField()
    received_quantity = serializers.ReadOnlyField()
    
    # Additional computed fields
    delivery_status_display = serializers.SerializerMethodField()
    total_outstanding_quantity = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()
    
    # Store details
    source_store_name = serializers.CharField(source='source_store.store_name', read_only=True)
    destination_store_name = serializers.CharField(source='destination_store.store_name', read_only=True)
    
    class Meta:
        model = SalesOrder
        fields = [
            'id', 'object_id', 'sales_order_id', 'source_store', 'destination_store',
            'source_store_name', 'destination_store_name', 'total_net_amount', 
            'order_date', 'delivery_status_code', 'delivery_status', 'delivery_status_display',
            'issued_quantity', 'received_quantity', 'total_outstanding_quantity',
            'completion_percentage', 'line_items', 'created_date', 'metadata'
        ]
    
    def get_delivery_status_display(self, obj):
        """Get human-readable delivery status"""
        status_dict = dict(obj.DELIVERY_STATUS_CHOICES)
        return status_dict.get(obj.delivery_status[0], 'Unknown')
    
    def get_total_outstanding_quantity(self, obj):
        """Calculate total outstanding quantity across all line items"""
        return sum(
            float(item.quantity) - float(item.received_quantity) 
            for item in obj.line_items.all()
        )
    
    def get_completion_percentage(self, obj):
        """Calculate completion percentage based on received vs ordered quantities"""
        total_ordered = sum(float(item.quantity) for item in obj.line_items.all())
        if total_ordered == 0:
            return 0
        return round((float(obj.received_quantity) / total_ordered) * 100, 2)


class GoodsIssueLineItemSerializer(serializers.ModelSerializer):
    # Product details from related sales order line item
    product_name = serializers.ReadOnlyField()
    product_id = serializers.ReadOnlyField()
    value_issued = serializers.ReadOnlyField()
    
    # Sales order line item details
    unit_price = serializers.DecimalField(
        source='sales_order_line_item.unit_price', 
        max_digits=15, decimal_places=3, read_only=True
    )
    unit_of_measurement = serializers.CharField(
        source='sales_order_line_item.unit_of_measurement', 
        read_only=True
    )
    
    class Meta:
        model = GoodsIssueLineItem
        fields = [
            'id', 'sales_order_line_item', 'product_id', 'product_name',
            'quantity_issued', 'unit_price', 'unit_of_measurement', 
            'value_issued', 'metadata'
        ]
    
    def validate_quantity_issued(self, value):
        """Validate that quantity issued is positive and doesn't exceed available quantity"""
        if value <= 0:
            raise serializers.ValidationError("Quantity issued must be greater than 0")
        
        # Additional validation will be handled in the model's clean method
        return value


class GoodsIssueLineItemCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating goods issue line items"""
    
    class Meta:
        model = GoodsIssueLineItem
        fields = ['sales_order_line_item', 'quantity_issued', 'metadata']
    
    def validate_quantity_issued(self, value):
        """Validate quantity issued"""
        if value <= 0:
            raise serializers.ValidationError("Quantity issued must be greater than 0")
        return value
    
    def validate(self, attrs):
        """Validate the entire line item"""
        try:
            # Create a temporary instance to run model validation
            temp_instance = GoodsIssueLineItem(**attrs)
            temp_instance.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
        return attrs


class GoodsIssueNoteSerializer(serializers.ModelSerializer):
    line_items = GoodsIssueLineItemSerializer(many=True, read_only=True)
    
    # Computed fields
    total_quantity_issued = serializers.ReadOnlyField()
    total_value_issued = serializers.ReadOnlyField()
    
    # Store and user details
    source_store_name = serializers.CharField(source='source_store.store_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    # Sales order details
    sales_order_id = serializers.IntegerField(source='sales_order.sales_order_id', read_only=True)
    destination_store_name = serializers.CharField(source='sales_order.destination_store.store_name', read_only=True)
    
    class Meta:
        model = GoodsIssueNote
        fields = [
            'id', 'sales_order', 'sales_order_id', 'issue_number', 
            'source_store', 'source_store_name', 'destination_store_name',
            'created_date', 'created_by', 'created_by_name',
            'posted_to_icg', 'posted_to_sap', 'total_quantity_issued', 
            'total_value_issued', 'line_items', 'metadata'
        ]


class GoodsIssueNoteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating goods issue notes"""
    line_items = GoodsIssueLineItemCreateSerializer(many=True, write_only=True)
    
    class Meta:
        model = GoodsIssueNote
        fields = ['sales_order', 'source_store', 'line_items', 'metadata']
    
    def validate(self, attrs):
        """Validate the goods issue note creation"""
        user = self.context['request'].user
        sales_order = attrs['sales_order']
        source_store = attrs['source_store']
        line_items = attrs['line_items']
        
        # Validate store authorization
        auth_service = AuthorizationService()
        if not auth_service.validate_store_access(user, source_store.id):
            raise serializers.ValidationError("You are not authorized to create goods issues for this store")
        
        # Validate that source store matches sales order
        if source_store != sales_order.source_store:
            raise serializers.ValidationError("Source store must match the sales order source store")
        
        # Validate line items exist and belong to the sales order
        if not line_items:
            raise serializers.ValidationError("At least one line item is required")
        
        for item_data in line_items:
            so_line_item = item_data['sales_order_line_item']
            if so_line_item.sales_order != sales_order:
                raise serializers.ValidationError(
                    f"Line item {so_line_item.id} does not belong to sales order {sales_order.id}"
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create goods issue note with line items"""
        line_items_data = validated_data.pop('line_items')
        user = self.context['request'].user
        
        # Create the goods issue note
        goods_issue = GoodsIssueNote.objects.create(
            created_by=user,
            **validated_data
        )
        
        # Create line items
        for item_data in line_items_data:
            GoodsIssueLineItem.objects.create(
                goods_issue=goods_issue,
                **item_data
            )
        
        return goods_issue


class TransferReceiptLineItemSerializer(serializers.ModelSerializer):
    # Product details from related goods issue line item
    product_name = serializers.ReadOnlyField()
    product_id = serializers.ReadOnlyField()
    value_received = serializers.ReadOnlyField()
    
    # Goods issue line item details
    quantity_issued = serializers.DecimalField(
        source='goods_issue_line_item.quantity_issued',
        max_digits=15, decimal_places=3, read_only=True
    )
    unit_price = serializers.DecimalField(
        source='goods_issue_line_item.sales_order_line_item.unit_price',
        max_digits=15, decimal_places=3, read_only=True
    )
    unit_of_measurement = serializers.CharField(
        source='goods_issue_line_item.sales_order_line_item.unit_of_measurement',
        read_only=True
    )
    
    class Meta:
        model = TransferReceiptLineItem
        fields = [
            'id', 'goods_issue_line_item', 'product_id', 'product_name',
            'quantity_issued', 'quantity_received', 'unit_price', 
            'unit_of_measurement', 'value_received', 'metadata'
        ]
    
    def validate_quantity_received(self, value):
        """Validate that quantity received is positive and doesn't exceed issued quantity"""
        if value <= 0:
            raise serializers.ValidationError("Quantity received must be greater than 0")
        
        # Additional validation will be handled in the model's clean method
        return value


class TransferReceiptLineItemCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating transfer receipt line items"""
    
    class Meta:
        model = TransferReceiptLineItem
        fields = ['goods_issue_line_item', 'quantity_received', 'metadata']
    
    def validate_quantity_received(self, value):
        """Validate quantity received"""
        if value <= 0:
            raise serializers.ValidationError("Quantity received must be greater than 0")
        return value
    
    def validate(self, attrs):
        """Validate the entire line item"""
        try:
            # Create a temporary instance to run model validation
            temp_instance = TransferReceiptLineItem(**attrs)
            temp_instance.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(str(e))
        return attrs


class TransferReceiptNoteSerializer(serializers.ModelSerializer):
    line_items = TransferReceiptLineItemSerializer(many=True, read_only=True)
    
    # Computed fields
    total_quantity_received = serializers.ReadOnlyField()
    total_value_received = serializers.ReadOnlyField()
    
    # Store and user details
    destination_store_name = serializers.CharField(source='destination_store.store_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    # Goods issue details
    goods_issue_number = serializers.IntegerField(source='goods_issue.issue_number', read_only=True)
    source_store_name = serializers.CharField(source='goods_issue.source_store.store_name', read_only=True)
    sales_order_id = serializers.IntegerField(source='goods_issue.sales_order.sales_order_id', read_only=True)
    
    class Meta:
        model = TransferReceiptNote
        fields = [
            'id', 'goods_issue', 'goods_issue_number', 'receipt_number',
            'destination_store', 'destination_store_name', 'source_store_name',
            'sales_order_id', 'created_date', 'created_by', 'created_by_name',
            'posted_to_icg', 'total_quantity_received', 'total_value_received',
            'line_items', 'metadata'
        ]


class TransferReceiptNoteCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating transfer receipt notes"""
    line_items = TransferReceiptLineItemCreateSerializer(many=True, write_only=True)
    
    class Meta:
        model = TransferReceiptNote
        fields = ['goods_issue', 'destination_store', 'line_items', 'metadata']
    
    def validate(self, attrs):
        """Validate the transfer receipt note creation"""
        user = self.context['request'].user
        goods_issue = attrs['goods_issue']
        destination_store = attrs['destination_store']
        line_items = attrs['line_items']
        
        # Validate store authorization
        auth_service = AuthorizationService()
        if not auth_service.validate_store_access(user, destination_store.id):
            raise serializers.ValidationError("You are not authorized to create transfer receipts for this store")
        
        # Validate that destination store matches sales order
        if destination_store != goods_issue.sales_order.destination_store:
            raise serializers.ValidationError("Destination store must match the sales order destination store")
        
        # Validate line items exist and belong to the goods issue
        if not line_items:
            raise serializers.ValidationError("At least one line item is required")
        
        for item_data in line_items:
            gi_line_item = item_data['goods_issue_line_item']
            if gi_line_item.goods_issue != goods_issue:
                raise serializers.ValidationError(
                    f"Line item {gi_line_item.id} does not belong to goods issue {goods_issue.id}"
                )
        
        return attrs
    
    def create(self, validated_data):
        """Create transfer receipt note with line items"""
        line_items_data = validated_data.pop('line_items')
        user = self.context['request'].user
        
        # Create the transfer receipt note
        transfer_receipt = TransferReceiptNote.objects.create(
            created_by=user,
            **validated_data
        )
        
        # Create line items
        for item_data in line_items_data:
            TransferReceiptLineItem.objects.create(
                transfer_receipt=transfer_receipt,
                **item_data
            )
        
        return transfer_receipt 