from rest_framework import serializers
from .models import Invoice, InvoiceLineItem, Surcharge


class SurchargeSerializer(serializers.ModelSerializer):
	class Meta:
		model = Surcharge
		fields = '__all__'


class InvoiceLineItemSerializer(serializers.ModelSerializer):
	# surcharges = SurchargeSerializer(many=True)
	po_line_item = serializers.SerializerMethodField()
	
	class Meta:
		model = InvoiceLineItem
		fields = ['po_line_item', 'quantity', 'surcharges', 'discountable', 'discount_type', 'discount']
	
	def create(self, validated_data):
		surcharge_data = validated_data.pop('surcharges')
		surcharges = Surcharge.objects.filter(id__in=surcharge_data)
		invoice_line_item = InvoiceLineItem.objects.create(**validated_data)
		invoice_line_item.surcharges.set(surcharges)
		return invoice_line_item
	
	def get_po_line_item(self, obj):
		return obj.po_line_item.id


class InvoiceSerializer(serializers.ModelSerializer):
	invoice_line_items = InvoiceLineItemSerializer(many=True)
	
	class Meta:
		model = Invoice
		fields = ['purchase_order', 'supplier', 'external_document_id', 'description', 'due_date', 'payment_terms',
		          'payment_reason', 'invoice_line_items']
	
	def create(self, validated_data):
		invoice_line_items = validated_data.pop('invoice_line_items')
		invoice = Invoice.objects.create(**validated_data)
		for line_item in invoice_line_items:
			InvoiceLineItem.objects.create(invoice=invoice, **line_item)
		return invoice
