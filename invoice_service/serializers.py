from rest_framework import serializers
from .models import Invoice, InvoiceLineItem, Surcharge


class SurchargeSerializer(serializers.ModelSerializer):
	class Meta:
		model = Surcharge
		fields = '__all__'


class InvoiceLineItemSerializer(serializers.ModelSerializer):
	surcharges = SurchargeSerializer(many=True)
	
	class Meta:
		model = InvoiceLineItem
		fields = ['po_line_item', 'quantity', 'surcharges', 'discountable', 'discount_type', 'discount']
	
	def create(self, validated_data):
		surcharge_data = validated_data.pop('surcharges')
		invoice_line_item = InvoiceLineItem.objects.create(**validated_data)
		for surcharge in surcharge_data:
			invoice_line_item.surcharges.add(Surcharge.objects.get(pk=surcharge['id']))
		return invoice_line_item


class InvoiceSerializer(serializers.ModelSerializer):
	invoice_line_items = InvoiceLineItemSerializer(many=True)
	
	class Meta:
		model = Invoice
		fields = ['purchase_order', 'supplier_document_id', 'description', 'due_date', 'payment_terms',
		          'payment_reason', 'invoice_line_items']
	
	def create(self, validated_data):
		line_items_data = validated_data.pop('invoice_line_items')
		invoice = Invoice.objects.create(**validated_data)
		for line_item_data in line_items_data:
			InvoiceLineItem.objects.create(invoice=invoice, **line_item_data)
		return invoice
