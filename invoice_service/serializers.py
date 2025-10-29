from rest_framework import serializers
from .models import Invoice, InvoiceLineItem
from core_service.serializers import VendorProfileSerializer
from egrn_service.serializers import (
	GoodsReceivedNoteSerializer,
	GoodsReceivedLineItemSerializer,
	PurchaseOrderSerializer,
	PurchaseOrderLineItemSerializer,
	StoreSerializer,
)
from egrn_service.models import GoodsReceivedNote, GoodsReceivedLineItem, PurchaseOrderLineItem
from approval_service.serializers import SignatureSerializer


class InvoiceLineItemSerializer(serializers.ModelSerializer):
	def __init__(self, *args, **kwargs):
		super(InvoiceLineItemSerializer, self).__init__(*args, **kwargs)
	
	def create(self, validated_data):
		invoice_line_item = InvoiceLineItem.objects.create(**validated_data)
		return invoice_line_item
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		# Use a lightweight GRN line item representation to avoid deep nested expansions
		grn_line_item = GoodsReceivedLineItemBriefSerializer(instance.grn_line_item).data
		serialized['grn_line_item'] = grn_line_item
		return serialized
	
	class Meta:
		model = InvoiceLineItem
		fields = ['invoice', 'quantity', 'gross_total', 'net_total', 'tax_amount', 'grn_line_item', 'po_line_item']
		write_only_fields = ['invoice', 'po_line_item']


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
		# Prefer prefetched signatures passed in via context to avoid N+1 queries
		signatures_by_id = self.context.get('signatures_by_id') if hasattr(self, 'context') else None
		if signatures_by_id is not None:
			signatures_list = signatures_by_id.get(obj.id, [])
			signatures = SignatureSerializer(signatures_list, many=True).data
		else:
			signatures = SignatureSerializer(obj.get_signatures(), many=True).data
		# We don't want to expose sensitive information about the signatories
		for signature in signatures:
			signature['signer'].pop('username')
			signature.pop('predecessor')
		# Return details about the workflow and signatures
		return {
			"signatories": obj.signatories,
			"pending_approval_from": obj.current_pending_signatory,
			"completed": obj.is_completely_signed,
			"approved": obj.is_accepted,
			"signatures": signatures,
		}
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		# Use a lightweight GRN serializer to avoid constructing heavy nested structures we later drop
		grn = GoodsReceivedNoteBriefSerializer(instance.grn).data if instance.grn else None
		if serialized.get('vendor') and 'byd_metadata' in serialized['vendor']:
			serialized['vendor'].pop('byd_metadata')
		serialized['grn'] = grn
		return serialized
	
	class Meta:
		model = Invoice
		fields = ['id', 'external_document_id','description', 'date_created', 'due_date', 'payment_terms',
				  'payment_reason', 'gross_total', 'total_tax_amount', 'net_total', 'invoice_line_items', 'workflow', 'grn', 'vendor', 'purchase_order']
		read_only_fields = ['id', 'gross_total', 'total_tax_amount', 'net_total']


class PurchaseOrderLineItemBriefSerializer(serializers.ModelSerializer):
	"""Lightweight PO line item serializer without nested GRN line items."""
	class Meta:
		model = PurchaseOrderLineItem
		fields = [
			'object_id', 'product_name', 'unit_price', 'quantity', 'delivered_quantity',
			'tax_rates', 'unit_of_measurement', 'extra_fields', 'metadata'
		]


class GoodsReceivedLineItemBriefSerializer(serializers.ModelSerializer):
	"""Lightweight GRN line item serializer with minimal PO line item fields."""
	purchase_order_line_item = serializers.SerializerMethodField()
	grn_number = serializers.SerializerMethodField()
	tax_value = serializers.SerializerMethodField()

	def get_purchase_order_line_item(self, obj):
		po_data = PurchaseOrderLineItemBriefSerializer(obj.purchase_order_line_item, many=False).data
		# Flatten commonly used location field out of metadata if present
		if 'metadata' in po_data and isinstance(po_data['metadata'], dict):
			# Drop heavy metadata block
			metadata = po_data['metadata']
			# Retain some product data for the invoice line item
			po_data['ItemShipToLocation']  = metadata.get('ItemShipToLocation', {})
			product_data = {
				'NetAmount': metadata.get('NetAmount'),
				'NetAmountCurrencyCode': metadata.get('NetAmountCurrencyCode'),
				'NetAmountCurrencyCodeText': metadata.get('NetAmountCurrencyCodeText'),
				'NetUnitPriceAmount': metadata.get('NetUnitPriceAmount'),
				'NetUnitPriceBaseQuantity': metadata.get('NetUnitPriceBaseQuantity'),
				'NetUnitPriceBaseUnitCode': metadata.get('NetUnitPriceBaseUnitCode'),
				'NetUnitPriceCurrencyCode': metadata.get('NetUnitPriceCurrencyCode'),
				'ProductCategoryInternalID': metadata.get('ProductCategoryInternalID'),
				'ProductID': metadata.get('ProductID'),
				'ProductSellerID': metadata.get('ProductSellerID'),
				'ProductStandardID': metadata.get('ProductStandardID'),
				'ProductTypeCode': metadata.get('ProductTypeCode'),
				'ProductTypeCodeText': metadata.get('ProductTypeCodeText'),
			}
			po_data['metadata'] = product_data
		return po_data

	def get_grn_number(self, obj):
		return obj.grn.grn_number if obj.grn else None

	def get_tax_value(self, obj):
		try:
			return float(obj.gross_value_received) - float(obj.net_value_received)
		except Exception:
			return None

	class Meta:
		model = GoodsReceivedLineItem
		fields = [
			'id', 'grn_number', 'quantity_received', 'gross_value_received', 'net_value_received',
			'invoiced_quantity', 'is_invoiced', 'tax_value', 'purchase_order_line_item'
		]


class GoodsReceivedNoteBriefSerializer(serializers.ModelSerializer):
	"""Lightweight GRN serializer with a compact purchase order representation."""
	purchase_order = serializers.SerializerMethodField()
	# Keep stores minimal via existing StoreSerializer; it's usually small
	stores = StoreSerializer(many=True, read_only=True)
	total_value_received = serializers.FloatField(source='total_net_value_received')

	def get_purchase_order(self, obj):
		po = obj.purchase_order
		return {
			'po_id': po.po_id,
			'object_id': po.object_id,
			'vendor': getattr(po.vendor, 'byd_internal_id', None),
			'total_net_amount': po.total_net_amount,
			'date': getattr(po, 'date', None),
			'delivery_status_code': po.delivery_status[0] if getattr(po, 'delivery_status', None) else None,
			'delivery_status_text': po.delivery_status[1] if getattr(po, 'delivery_status', None) else None,
			'delivery_completed': True if getattr(po, 'delivery_status', None) and po.delivery_status[0] == '3' else False,
		}

	class Meta:
		model = GoodsReceivedNote
		fields = [
			'grn_number', 'created', 'total_value_received', 'invoiced_quantity', 'invoice_status_code',
			'invoice_status_text', 'stores', 'purchase_order'
		]