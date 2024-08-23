from rest_framework import serializers
from .models import Invoice, InvoiceLineItem
from core_service.serializers import VendorProfileSerializer
from egrn_service.serializers import GoodsReceivedNoteSerializer, GoodsReceivedLineItemSerializer, PurchaseOrderSerializer, PurchaseOrderLineItemSerializer
from approval_service.serializers import SignatureSerializer


class InvoiceLineItemSerializer(serializers.ModelSerializer):
	def __init__(self, *args, **kwargs):
		super(InvoiceLineItemSerializer, self).__init__(*args, **kwargs)
	
	def create(self, validated_data):
		invoice_line_item = InvoiceLineItem.objects.create(**validated_data)
		return invoice_line_item
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		purchase_order_line_item = PurchaseOrderLineItemSerializer(instance.po_line_item, read_only=True).data
		purchase_order_line_item.pop('metadata')
		grn_line_item = GoodsReceivedLineItemSerializer(instance.grn_line_item).data
		grn_line_item.pop('purchase_order_line_item')
		
		serialized['po_line_item'] = purchase_order_line_item
		serialized['grn_line_item'] = grn_line_item
		
		return serialized
	
	class Meta:
		model = InvoiceLineItem
		fields = ['invoice', 'quantity', 'gross_total', 'net_total', 'tax_amount', 'grn_line_item', 'po_line_item']
		write_only_fields = ['invoice']


class InvoiceSerializer(serializers.ModelSerializer):
	invoice_line_items = InvoiceLineItemSerializer(many=True, read_only=True)
	gross_total = serializers.SerializerMethodField()
	total_tax_amount = serializers.SerializerMethodField()
	net_total = serializers.SerializerMethodField()
	workflow = serializers.SerializerMethodField()
	vendor = VendorProfileSerializer(read_only=True, source='grn.purchase_order.vendor')
	
	def create(self, validated_data):
		invoice = Invoice.objects.create(**validated_data)
		return invoice
	
	def get_gross_total(self, obj):
		return obj.gross_total
	
	def get_total_tax_amount(self, obj):
		return obj.total_tax_amount

	def get_net_total(self, obj):
		return obj.net_total
	
	def get_workflow(self, obj):
		# Get and serialize the signatures
		signatures = SignatureSerializer(obj.get_signatures(), many=True).data
		# We don't want to expose sensitive information about the signatories
		for signature in signatures:
			signature.pop('signer')
			signature.pop('predecessor')
		# Return details about the workflow and signatures
		return {
			"completed": obj.is_completely_signed,
			"pending_approval_from": obj.current_pending_signatory,
			"approved": obj.is_accepted,
			"signatures": signatures,
		}
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		purchase_order = PurchaseOrderSerializer(instance.purchase_order).data
		purchase_order.pop('Item')
		purchase_order.pop('metadata')
		grn = GoodsReceivedNoteSerializer(instance.grn).data
		grn.pop('purchase_order')
		grn.pop('grn_line_items')
		
		serialized['purchase_order'] = purchase_order
		serialized['grn'] = grn
		return serialized
	
	class Meta:
		model = Invoice
		fields = ['id', 'external_document_id','description', 'date_created', 'due_date', 'payment_terms',
				  'payment_reason', 'gross_total', 'total_tax_amount', 'net_total', 'invoice_line_items', 'workflow', 'grn', 'purchase_order', 'vendor']
		read_only_fields = ['id', 'gross_total', 'total_tax_amount', 'net_total']