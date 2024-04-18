from rest_framework import serializers
from .models import Invoice, InvoiceLineItem, Surcharge
from egrn_service.models import PurchaseOrder, PurchaseOrderLineItem
from egrn_service.serializers import PurchaseOrderSerializer, PurchaseOrderLineItemSerializer


class SurchargeSerializer(serializers.ModelSerializer):
	class Meta:
		model = Surcharge
		fields = '__all__'
		
class InvoiceLineItemSerializer(serializers.ModelSerializer):
	surcharges = SurchargeSerializer(many=True, read_only=True)
	surcharge_ids = serializers.ListField(
		child=serializers.IntegerField(),
		write_only=True
	)
	net_total_after_surcharges = serializers.SerializerMethodField()
	
	def __init__(self, *args, **kwargs):
		super(InvoiceLineItemSerializer, self).__init__(*args, **kwargs)
	
	def create(self, validated_data):
		surcharges = validated_data.pop('surcharge_ids')
		invoice_line_item = InvoiceLineItem.objects.create(**validated_data)
		invoice_line_item.surcharges.set(surcharges)
		invoice_line_item.set_surcharge_and_net(invoice_line_item.surcharges.all())
		return invoice_line_item
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		purchase_order_line_item = PurchaseOrderLineItemSerializer(instance.po_line_item, read_only=True).data
		purchase_order_line_item.pop('metadata')
		serialized['po_line_item'] = purchase_order_line_item
		return serialized
	
	def get_net_total_after_surcharges(self, obj):
		return obj.net_total
	
	def get_po_line_item(self, obj):
		return obj.po_line_item
	
	class Meta:
		model = InvoiceLineItem
		fields = ['invoice', 'quantity', 'gross_total', 'discountable', 'discount_type', 'discount', 'discount_amount', 'discounted_gross_total', 'net_total_after_surcharges', 'surcharges', 'po_line_item', 'surcharge_ids']
		write_only_fields = ['invoice']

class InvoiceSerializer(serializers.ModelSerializer):
	invoice_line_items = InvoiceLineItemSerializer(many=True, read_only=True)
	gross_total = serializers.SerializerMethodField()
	total_discount_amount = serializers.SerializerMethodField()
	discounted_gross_total = serializers.SerializerMethodField()
	total_tax_amount = serializers.SerializerMethodField()
	net_total = serializers.SerializerMethodField()
	
	def create(self, validated_data):
		invoice = Invoice.objects.create(**validated_data)
		return invoice
	
	def get_gross_total(self, obj):
		return obj.gross_total

	def get_total_discount_amount(self, obj):
		return obj.total_discount_amount
	
	def get_discounted_gross_total(self, obj):
		return obj.discounted_gross_total
	
	def get_total_tax_amount(self, obj):
		return obj.total_surcharge_amount

	def get_net_total(self, obj):
		return obj.net_total
	
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
		          'payment_reason', 'gross_total', 'total_discount_amount', 'discounted_gross_total', 'total_tax_amount', 'net_total', 'invoice_line_items', 'purchase_order']
		read_only_fields = ['id', 'gross_total', 'total_discount_amount', 'discounted_gross_total', 'total_tax_amount', 'net_total']