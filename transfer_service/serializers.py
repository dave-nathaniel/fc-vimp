from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import (
    TransferReceiptNote, TransferReceiptLineItem,
    InboundDelivery, InboundDeliveryLineItem
)
from egrn_service.models import Store
from .validators import (
    FieldValidator, TransferReceiptValidator,
    StoreAuthorizationValidator
)


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

    def get_destination_store(self, obj):
        return Store.objects.get(id=obj.destination_store.id)
    
    class Meta:
        model = InboundDelivery
        fields = [
            'id', 'object_id', 'delivery_id', 'source_location_id', 'source_location_name',
            'destination_store', 'delivery_date', 'delivery_status_code', 'delivery_status',
            'delivery_type_code', 'sales_order_reference', 'total_quantity_expected', 
            'total_quantity_received', 'is_fully_received', 'destination_store_name',
            'line_items', 'metadata', 'created_date'
        ]


class TransferReceiptLineItemSerializer(serializers.ModelSerializer):
    # Product details from related inbound delivery line item
    inbound_delivery_line_item = InboundDeliveryLineItemSerializer(read_only=True)
    product_id = serializers.ReadOnlyField(source='inbound_delivery_line_item.product_id')
    value_received = serializers.ReadOnlyField()
    
    # Inbound delivery line item details
    quantity_expected = serializers.DecimalField(
        source='inbound_delivery_line_item.quantity_expected',
        max_digits=15, decimal_places=3, read_only=True
    )
    unit_of_measurement = serializers.CharField(
        source='inbound_delivery_line_item.unit_of_measurement',
        read_only=True
    )
    
    class Meta:
        model = TransferReceiptLineItem
        fields = [
            'id', 'inbound_delivery_line_item', 'product_id',
            'quantity_expected', 'quantity_received', 
            'unit_of_measurement', 'value_received', 'metadata'
        ]
    
    def validate_quantity_received(self, value):
        """Validate that received quantity is valid"""
        if value <= 0:
            raise serializers.ValidationError("Quantity received must be greater than 0")
        return value
    
    def validate(self, attrs):
        """Validate the entire line item"""
        inbound_delivery_line_item = attrs.get('inbound_delivery_line_item')
        quantity_received = attrs.get('quantity_received')
        
        if inbound_delivery_line_item and quantity_received:
            # Check if receiving this quantity would exceed the expected quantity
            current_received = inbound_delivery_line_item.quantity_received
            total_received = current_received + quantity_received
            
            if total_received > inbound_delivery_line_item.quantity_expected:
                raise serializers.ValidationError({
                    'quantity_received': f'Total received quantity ({total_received}) would exceed expected quantity ({inbound_delivery_line_item.quantity_expected})'
                })
        
        return attrs


class TransferReceiptNoteSerializer(serializers.ModelSerializer):
    line_items = TransferReceiptLineItemSerializer(many=True, read_only=True)
    
    # Store and user details
    destination_store = serializers.CharField(source='inbound_delivery.destination_store.store_name', read_only=True)
    created_by = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    # Inbound delivery details
    inbound_delivery = InboundDeliverySerializer(read_only=True)
    source_location = serializers.CharField(source='inbound_delivery.source_location_name', read_only=True)
    source_location_id = serializers.CharField(source='inbound_delivery.source_location_id', read_only=True)
    
    class Meta:
        model = TransferReceiptNote
        fields = [
            'id', 'receipt_number', 'inbound_delivery', 'notes', 'source_location', 'source_location_id', 'destination_store',
            'created_date', 'created_by', 'posted_to_icg', 'line_items', 'metadata'
        ]
        read_only_fields = ['inbound_delivery', 'receipt_number', 'created_by']

    def validate(self, data):
        """Validate the entire inbound delivery receipt"""
        inbound_delivery_id = self.initial_data.get('delivery')
        if not inbound_delivery_id:
            raise serializers.ValidationError({"delivery": ["delivery is required"]})
        try:
            inbound_delivery = InboundDelivery.objects.get(id=inbound_delivery_id)
        except InboundDelivery.DoesNotExist:
            raise serializers.ValidationError({"delivery": ["Inbound delivery not found"]})

        inbound_delivery_line_items = inbound_delivery.line_items.all()
        received_line_items = self.initial_data.get('line_items', [])
        
        if not isinstance(received_line_items, list) or not received_line_items:
            raise serializers.ValidationError({"line_items": ["At least one line item is required"]})

        # Ensure all line items belong to this delivery
        for item in received_line_items:
            delivery_line_item_id = item.get('delivery_line_item')
            if delivery_line_item_id is None:
                raise serializers.ValidationError({"line_items": ["Each item must include delivery_line_item"]})
            inbound_delivery_line_item = inbound_delivery_line_items.filter(
                id=delivery_line_item_id
            ).first()
            if not inbound_delivery_line_item:
                raise serializers.ValidationError(
                    {"line_items": ["All line items must belong to the specified inbound delivery"]}
                )
            qty = item.get('quantity_received')
            if qty is None:
                raise serializers.ValidationError({"line_items": ["Each item must include quantity_received"]})
            try:
                from decimal import Decimal
                qty_dec = Decimal(str(qty))
            except Exception:
                raise serializers.ValidationError({"line_items": ["quantity_received must be a number"]})
            if qty_dec <= 0:
                raise serializers.ValidationError({"line_items": ["quantity_received must be greater than 0"]})
            total_received = inbound_delivery_line_item.quantity_received + qty_dec
            if total_received > inbound_delivery_line_item.quantity_expected:
                raise serializers.ValidationError({
                    "line_items": [
                        f"Total received ({total_received}) exceeds expected ({inbound_delivery_line_item.quantity_expected}) for {inbound_delivery_line_item.product_name}"
                    ]
                })

        return data
    
    def create(self, validated_data):
        """Create inbound delivery receipt note with line items"""
        from django.db import transaction
        from decimal import Decimal
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        inbound_delivery_id = self.initial_data.get('delivery')
        notes = self.initial_data.get('notes')
        line_items = self.initial_data.get('line_items', [])

        inbound_delivery = InboundDelivery.objects.get(id=inbound_delivery_id)

        with transaction.atomic():
            # Create the transfer receipt note
            receipt = TransferReceiptNote(
                inbound_delivery=inbound_delivery,
                notes=notes,
                created_by=user
            )
            receipt.save()

            # Create line items and update inbound delivery line items
            for item in line_items:
                inbound_delivery_line_item = InboundDeliveryLineItem.objects.get(
                    id=item.get('delivery_line_item')
                )
                quantity_received = Decimal(str(item.get('quantity_received')))

                # Create TR line item
                TransferReceiptLineItem.objects.create(
                    transfer_receipt=receipt,
                    inbound_delivery_line_item=inbound_delivery_line_item,
                    quantity_received=quantity_received,
                    metadata=item.get('metadata', {})
                )

                # Update inbound delivery line item received quantity
                inbound_delivery_line_item.quantity_received = (
                    Decimal(str(inbound_delivery_line_item.quantity_received)) + quantity_received
                )
                inbound_delivery_line_item.save()

            # Update delivery status
            inbound_delivery.refresh_from_db()
            if inbound_delivery.is_fully_received:
                inbound_delivery.delivery_status_code = '3'  # Completed
            else:
                inbound_delivery.delivery_status_code = '2'  # In Process
            inbound_delivery.save()

            return receipt