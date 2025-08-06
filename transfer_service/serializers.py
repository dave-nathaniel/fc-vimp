from rest_framework import serializers
from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import (
    SalesOrder, SalesOrderLineItem,
    GoodsIssueNote, GoodsIssueLineItem,
    TransferReceiptNote, TransferReceiptLineItem,
    InboundDelivery, InboundDeliveryLineItem
)
from .services import AuthorizationService
from .validators import (
    FieldValidator, GoodsIssueValidator, TransferReceiptValidator,
    StoreAuthorizationValidator
)


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
        try:
            return FieldValidator.validate_positive_decimal(value, "quantity_issued")
        except DjangoValidationError as e:
            field_errors = e.error_dict if hasattr(e, 'error_dict') else {"quantity_issued": [str(e)]}
            if "quantity_issued" in field_errors:
                raise serializers.ValidationError(field_errors["quantity_issued"][0])
            raise serializers.ValidationError(str(e))


class GoodsIssueLineItemCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating goods issue line items"""
    
    class Meta:
        model = GoodsIssueLineItem
        fields = ['sales_order_line_item', 'quantity_issued', 'metadata']
    
    def validate_quantity_issued(self, value):
        """Validate quantity issued"""
        try:
            return FieldValidator.validate_positive_decimal(value, "quantity_issued")
        except DjangoValidationError as e:
            field_errors = e.error_dict if hasattr(e, 'error_dict') else {"quantity_issued": [str(e)]}
            if "quantity_issued" in field_errors:
                raise serializers.ValidationError(field_errors["quantity_issued"][0])
            raise serializers.ValidationError(str(e))
    
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
        
        # Enhanced store authorization validation
        try:
            StoreAuthorizationValidator.validate_store_access(
                user, 
                source_store.id,
                required_roles=['manager', 'assistant']
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError("You are not authorized to create goods issues for this store")
        
        # Comprehensive goods issue validation
        try:
            GoodsIssueValidator.validate_goods_issue_creation(
                sales_order, source_store, line_items, user
            )
        except DjangoValidationError as e:
            if hasattr(e, 'error_dict'):
                # Convert field errors to DRF format
                field_errors = {}
                for field, errors in e.error_dict.items():
                    field_errors[field] = [str(error) for error in errors]
                raise serializers.ValidationError(field_errors)
            elif hasattr(e, 'error_list'):
                # Convert general errors to DRF format
                raise serializers.ValidationError(e.error_list)
            else:
                raise serializers.ValidationError(str(e))
        
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
        try:
            return FieldValidator.validate_positive_decimal(value, "quantity_received")
        except DjangoValidationError as e:
            field_errors = e.error_dict if hasattr(e, 'error_dict') else {"quantity_received": [str(e)]}
            if "quantity_received" in field_errors:
                raise serializers.ValidationError(field_errors["quantity_received"][0])
            raise serializers.ValidationError(str(e))


class TransferReceiptLineItemCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating transfer receipt line items"""
    
    class Meta:
        model = TransferReceiptLineItem
        fields = ['goods_issue_line_item', 'quantity_received', 'metadata']
    
    def validate_quantity_received(self, value):
        """Validate quantity received"""
        try:
            return FieldValidator.validate_positive_decimal(value, "quantity_received")
        except DjangoValidationError as e:
            field_errors = e.error_dict if hasattr(e, 'error_dict') else {"quantity_received": [str(e)]}
            if "quantity_received" in field_errors:
                raise serializers.ValidationError(field_errors["quantity_received"][0])
            raise serializers.ValidationError(str(e))
    
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
        
        # Enhanced store authorization validation
        try:
            StoreAuthorizationValidator.validate_store_access(
                user, 
                destination_store.id,
                required_roles=['manager', 'assistant']
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError("You are not authorized to create transfer receipts for this store")
        
        # Comprehensive transfer receipt validation
        try:
            TransferReceiptValidator.validate_transfer_receipt_creation(
                goods_issue, destination_store, line_items, user
            )
        except DjangoValidationError as e:
            if hasattr(e, 'error_dict'):
                # Convert field errors to DRF format
                field_errors = {}
                for field, errors in e.error_dict.items():
                    field_errors[field] = [str(error) for error in errors]
                raise serializers.ValidationError(field_errors)
            elif hasattr(e, 'error_list'):
                # Convert general errors to DRF format
                raise serializers.ValidationError(e.error_list)
            else:
                raise serializers.ValidationError(str(e))
        
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


class InboundDeliveryLineItemSerializer(serializers.ModelSerializer):
    # Computed fields
    quantity_outstanding = serializers.ReadOnlyField()
    is_fully_received = serializers.ReadOnlyField()
    
    class Meta:
        model = InboundDeliveryLineItem
        fields = [
            'id', 'object_id', 'product_id', 'product_name',
            'quantity_expected', 'quantity_received', 'unit_of_measurement',
            'quantity_outstanding', 'is_fully_received', 'metadata'
        ]


class InboundDeliverySerializer(serializers.ModelSerializer):
    line_items = InboundDeliveryLineItemSerializer(many=True, read_only=True)
    
    # Computed fields
    delivery_status = serializers.ReadOnlyField()
    total_quantity_expected = serializers.ReadOnlyField()
    total_quantity_received = serializers.ReadOnlyField()
    is_fully_received = serializers.ReadOnlyField()
    
    # Store and location details
    destination_store_name = serializers.CharField(source='destination_store.store_name', read_only=True)
    
    class Meta:
        model = InboundDelivery
        fields = [
            'id', 'object_id', 'delivery_id', 'source_location_id', 'source_location_name',
            'destination_store', 'delivery_date', 'delivery_status_code', 'delivery_status',
            'delivery_type_code', 'sales_order_reference', 'total_quantity_expected', 
            'total_quantity_received', 'is_fully_received', 'destination_store_name',
            'line_items', 'metadata', 'created_date'
        ]


class DeliveryReceiptLineItemSerializer(serializers.ModelSerializer):
    """Serializer for receiving goods from a delivery line item"""
    
    # Read-only fields from the delivery line item
    product_id = serializers.CharField(source='delivery_line_item.product_id', read_only=True)
    product_name = serializers.CharField(source='delivery_line_item.product_name', read_only=True)
    quantity_expected = serializers.DecimalField(
        source='delivery_line_item.quantity_expected',
        max_digits=15, decimal_places=3, read_only=True
    )
    unit_of_measurement = serializers.CharField(
        source='delivery_line_item.unit_of_measurement', read_only=True
    )
    
    # Field for entering received quantity
    delivery_line_item = serializers.PrimaryKeyRelatedField(queryset=InboundDeliveryLineItem.objects.all())
    quantity_received = serializers.DecimalField(max_digits=15, decimal_places=3)
    
    class Meta:
        model = InboundDeliveryLineItem
        fields = [
            'delivery_line_item', 'product_id', 'product_name',
            'quantity_expected', 'quantity_received', 'unit_of_measurement'
        ]
    
    def validate_quantity_received(self, value):
        """Validate that received quantity is valid"""
        if value <= 0:
            raise serializers.ValidationError("Quantity received must be greater than 0")
        return value
    
    def validate(self, attrs):
        """Validate the entire line item"""
        delivery_line_item = attrs.get('delivery_line_item')
        quantity_received = attrs.get('quantity_received')
        
        if delivery_line_item and quantity_received:
            # Check if receiving this quantity would exceed the expected quantity
            current_received = delivery_line_item.quantity_received
            total_received = current_received + quantity_received
            
            if total_received > delivery_line_item.quantity_expected:
                raise serializers.ValidationError({
                    'quantity_received': f'Total received quantity ({total_received}) would exceed expected quantity ({delivery_line_item.quantity_expected})'
                })
        
        return attrs


class DeliveryReceiptSerializer(serializers.Serializer):
    """Serializer for creating a receipt from an inbound delivery"""
    delivery = serializers.PrimaryKeyRelatedField(queryset=InboundDelivery.objects.all())
    line_items = DeliveryReceiptLineItemSerializer(many=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_line_items(self, value):
        """Validate line items for the delivery receipt"""
        if not value:
            raise serializers.ValidationError("At least one line item is required")
        
        # Check that all line items belong to the same delivery
        deliveries = set()
        for item in value:
            delivery_line_item = item.get('delivery_line_item')
            if delivery_line_item:
                deliveries.add(delivery_line_item.delivery.id)
        
        if len(deliveries) > 1:
            raise serializers.ValidationError("All line items must belong to the same delivery")
        
        return value
    
    def validate(self, attrs):
        """Validate the entire delivery receipt"""
        delivery = attrs.get('delivery')
        line_items = attrs.get('line_items', [])
        
        if delivery and line_items:
            # Ensure all line items belong to this delivery
            for item in line_items:
                delivery_line_item = item.get('delivery_line_item')
                if delivery_line_item and delivery_line_item.delivery != delivery:
                    raise serializers.ValidationError(
                        "All line items must belong to the specified delivery"
                    )
        
        return attrs 