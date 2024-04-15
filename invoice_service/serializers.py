from rest_framework import serializers
from .models import Invoice, InvoiceLineItem, Surcharge
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem
from egrn_service.serializers import PurchaseOrderSerializer, PurchaseOrderLineItemSerializer


class SurchargeSerializer(serializers.ModelSerializer):
	class Meta:
		model = Surcharge
		fields = '__all__'

class InvoiceSerializer(serializers.ModelSerializer):
	invoice_line_items = serializers.SerializerMethodField()
	
	def create(self, validated_data):
		invoice = Invoice.objects.create(**validated_data)
		return invoice
	
	def get_invoice_line_items(self, obj):
		return InvoiceLineItemSerializer(obj.invoice_line_items, many=True).data
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		purchase_order = PurchaseOrderSerializer(instance.purchase_order, read_only=True).data
		purchase_order.pop('Item')
		purchase_order.pop('metadata')
		serialized['purchase_order'] = purchase_order
		return serialized
	
	class Meta:
		model = Invoice
		fields = ['id', 'external_document_id', 'description', 'due_date', 'payment_terms',
		          'payment_reason', 'purchase_order', 'invoice_line_items']
		read_only_fields = ['id']
		
class InvoiceLineItemSerializer(serializers.ModelSerializer):
	surcharges = SurchargeSerializer(many=True, read_only=True)
	surcharge_ids = serializers.ListField(
		child=serializers.IntegerField(),
		write_only=True
	)
	gross_total = serializers.SerializerMethodField()
	
	def create(self, validated_data):
		surcharge_ids = validated_data.pop('surcharge_ids')
		invoice_line_item = InvoiceLineItem.objects.create(**validated_data)
		invoice_line_item.surcharges.set(surcharge_ids)
		
		return invoice_line_item
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		purchase_order_line_item = PurchaseOrderLineItemSerializer(instance.po_line_item, read_only=True).data
		purchase_order_line_item.pop('metadata')
		serialized['po_line_item'] = purchase_order_line_item
		return serialized
	
	def get_gross_total(self, obj):
		return obj.gross_total
	
	def get_po_line_item(self, obj):
		return obj.po_line_item
	
	class Meta:
		model = InvoiceLineItem
		fields = ['invoice', 'quantity', 'gross_total', 'discountable', 'discount_type', 'discount', 'surcharges',
		          'surcharge_ids', 'po_line_item']
