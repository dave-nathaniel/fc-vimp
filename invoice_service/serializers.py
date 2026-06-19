from decimal import Decimal

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
		# Use a lightweight GRN line item representation to avoid deep nested expansions.
		# Forward context so optimisation maps reach the nested PO line item serializer.
		grn_line_item = GoodsReceivedLineItemBriefSerializer(
			instance.grn_line_item, context=self.context
		).data if instance.grn_line_item else None
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
	
	# Prefer values pre-annotated on the queryset to avoid per-row aggregates
	def get_gross_total(self, obj):
		return getattr(obj, 'gross_total_annotated', obj.gross_total)

	def get_total_tax_amount(self, obj):
		return getattr(obj, 'total_tax_amount_annotated', obj.total_tax_amount)

	def get_net_total(self, obj):
		return getattr(obj, 'net_total_annotated', obj.net_total)
	
	def get_workflow(self, obj):
		# Prefer prefetched signatures passed in via context to avoid N+1 queries
		signatures_by_id = self.context.get('signatures_by_id') if hasattr(self, 'context') else None
		if signatures_by_id is not None:
			signatures_list = signatures_by_id.get(obj.id, [])
			signatures = SignatureSerializer(signatures_list, many=True).data
		else:
			signatures_list = list(obj.get_signatures())
			signatures = SignatureSerializer(signatures_list, many=True).data
		# We don't want to expose sensitive information about the signatories
		for signature in signatures:
			signature['signer'].pop('username')
			signature.pop('predecessor')
		# Derive completion/approval from the prefetched signature list instead of
		# obj.is_completely_signed / obj.is_accepted, which each re-query signatures
		# per row (get_signatures + get_last_signature), defeating the prefetch.
		completed, approved = self._workflow_state(obj, signatures_list)
		# Return details about the workflow and signatures
		return {
			"signatories": obj.signatories,
			"pending_approval_from": obj.current_pending_signatory,
			"completed": completed,
			"approved": approved,
			"signatures": signatures,
		}

	def _workflow_state(self, obj, signatures_list):
		"""
		Compute (completed, approved) from an in-memory signature list ordered by
		-date_signed (latest first), mirroring Signable.is_completely_signed /
		is_rejected / is_accepted without hitting the database.
		"""
		signatories = obj.signatories or []
		num_signed = len(signatures_list)
		# is_rejected: latest signature was a rejection.
		latest = signatures_list[0] if signatures_list else None
		is_rejected = (latest.accepted is False) if latest is not None else False
		# is_completely_signed: every signatory has signed, OR it was rejected.
		completed = (num_signed == len(signatories)) or is_rejected
		# is_accepted: completed and not rejected.
		approved = (is_rejected is False) if completed else False
		return completed, approved
	
	def to_representation(self, instance):
		serialized = super().to_representation(instance)
		# Use a lightweight GRN serializer to avoid constructing heavy nested structures we later drop.
		# Forward context so optimisation maps (e.g. product_config_map) reach nested serializers.
		grn = GoodsReceivedNoteBriefSerializer(
			instance.grn, context=self.context
		).data if instance.grn else None
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
	# Both of these were model properties that ran one query PER line item:
	#   - delivered_quantity -> .aggregate(Sum('quantity_received'))
	#   - extra_fields       -> ProductConfiguration.objects.get(product_id=...)
	# Resolve them from prefetched / context-provided data instead. Falls back to
	# the model property when the optimisation context is absent (e.g. other callers).
	delivered_quantity = serializers.SerializerMethodField()
	extra_fields = serializers.SerializerMethodField()

	def get_delivered_quantity(self, obj):
		grn_items = getattr(obj, '_prefetched_objects_cache', {}).get('grn_line_item')
		if grn_items is None:
			return obj.delivered_quantity  # fallback: model property (its own aggregate)
		return sum(float(g.quantity_received) for g in grn_items) or 0.0

	def get_extra_fields(self, obj):
		# A {product_id: conversion_field} map can be supplied via context to avoid
		# a ProductConfiguration query per line item.
		config_map = self.context.get('product_config_map') if hasattr(self, 'context') else None
		if config_map is not None:
			product_id = (obj.metadata or {}).get('ProductID')
			return config_map.get(product_id, [])
		return obj.extra_fields  # fallback: model property (its own query)

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
	# Model properties invoiced_quantity / is_invoiced each run an aggregate per
	# line item. Resolve from the prefetched invoice_items cache instead.
	invoiced_quantity = serializers.SerializerMethodField()
	is_invoiced = serializers.SerializerMethodField()

	def _invoiced_quantity_decimal(self, obj):
		# Keep Decimal precision: the original is_invoiced compared exact Decimals,
		# and float summation can flip a fully-invoiced line's status.
		inv_items = getattr(obj, '_prefetched_objects_cache', {}).get('invoice_items')
		if inv_items is None:
			return obj.invoiced_quantity  # fallback: model property (Decimal aggregate)
		return sum((inv.quantity for inv in inv_items), Decimal('0'))

	def get_invoiced_quantity(self, obj):
		# Field historically serialized as a number; preserve that shape.
		return float(self._invoiced_quantity_decimal(obj))

	def get_is_invoiced(self, obj):
		return self._invoiced_quantity_decimal(obj) == obj.quantity_received

	def get_purchase_order_line_item(self, obj):
		# Forward context so product_config_map / prefetch optimisations reach the
		# PO line item serializer (manual instantiation does not inherit context).
		po_data = PurchaseOrderLineItemBriefSerializer(
			obj.purchase_order_line_item, many=False, context=self.context
		).data
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


# --- Optimised version ---

class GoodsReceivedNoteBriefSerializer(serializers.ModelSerializer):
	"""Lightweight GRN serializer that avoids per-line SQL aggregates."""
	# lightweight PO representation
	purchase_order = serializers.SerializerMethodField()
	stores = StoreSerializer(many=True, read_only=True)
	total_value_received = serializers.FloatField(source='total_net_value_received')
	# compute quantities & status efficiently
	invoiced_quantity = serializers.SerializerMethodField()
	invoice_status_code = serializers.SerializerMethodField()
	invoice_status_text = serializers.SerializerMethodField()
	grn_line_items = GoodsReceivedLineItemBriefSerializer(many=True, read_only=True)
	
	def get_purchase_order(self, obj):
		po = obj.purchase_order
		# Compute delivery status ONCE from prefetched data instead of calling
		# po.delivery_status (a model property whose per-line .aggregate() bypasses
		# the prefetch cache and fired ~1700 SUM queries per page). The parent
		# queryset prefetches grn__purchase_order__line_items__grn_line_item, so the
		# received quantities are already in memory.
		status_code, status_text = self._po_delivery_status(po)
		return {
			'po_id': po.po_id,
			'object_id': po.object_id,
			'vendor': getattr(po.vendor, 'byd_internal_id', None),
			'total_net_amount': po.total_net_amount,
			'date': getattr(po, 'date', None),
			'delivery_status_code': status_code,
			'delivery_status_text': status_text,
			'delivery_completed': status_code == '3',
		}

	def _po_delivery_status(self, po):
		"""
		Derive a PurchaseOrder's (code, text) delivery status from prefetched line
		items. Faithfully mirrors PurchaseOrder.delivery_status (which relies on
		PurchaseOrderLineItem.delivery_status) but consumes the prefetch cache, so
		it costs zero queries per row instead of one SUM aggregate per line item.

		Per-line status (from the model):
		  delivered == 0            -> '1' (Not Delivered)
		  0 < delivered < ordered   -> '2' (Partially Delivered)
		  delivered == ordered      -> '3' (Completely Delivered)
		PO rollup (from the model):
		  all lines '3'                       -> '3'
		  else any line '2' or '3'            -> '2'
		  else                                -> '1'
		"""
		status_codes = po.delivery_status_code  # [('1', ...), ('2', ...), ('3', ...)]
		po_line_items = getattr(po, '_prefetched_objects_cache', {}).get('line_items')
		if po_line_items is None:
			po_line_items = po.line_items.all()

		per_line = []
		for po_li in po_line_items:
			grn_items = getattr(po_li, '_prefetched_objects_cache', {}).get('grn_line_item')
			if grn_items is None:
				grn_items = po_li.grn_line_item.all()
			# Decimal precision mirrors the model property's exact comparison.
			delivered = sum((g.quantity_received for g in grn_items), Decimal('0'))
			ordered = po_li.quantity
			if delivered == 0:
				per_line.append('1')
			elif delivered < ordered:
				per_line.append('2')
			elif delivered == ordered:
				per_line.append('3')
			else:
				# Over-delivery: model's elif chain leaves status undefined (None);
				# treat as complete to avoid a missing code in the payload.
				per_line.append('3')

		if per_line and all(code == '3' for code in per_line):
			return status_codes[2]
		if any(code in ('2', '3') for code in per_line):
			return status_codes[1]
		return status_codes[0]

	def _prefetched_line_items(self, obj):
		"""Return prefetched GRN line items if available, else fallback to DB."""
		return getattr(obj, '_prefetched_objects_cache', {}).get('line_items') or obj.line_items.all()

	def get_invoiced_quantity(self, obj):
		# Sum quantities from prefetched invoice_items to avoid per-line aggregates
		total = 0
		for grn_li in self._prefetched_line_items(obj):
			inv_items = getattr(grn_li, '_prefetched_objects_cache', {}).get('invoice_items') or grn_li.invoice_items.all()
			for inv in inv_items:
				total += float(inv.quantity)
		return total

	def get_invoice_status_code(self, obj):
		completed = all(self._grn_line_item_is_fully_invoiced(li) for li in self._prefetched_line_items(obj))
		in_process = any(self._grn_line_item_has_any_invoice(li) for li in self._prefetched_line_items(obj))
		if completed:
			return '3'
		elif in_process:
			return '2'
		return '1'

	def get_invoice_status_text(self, obj):
		code = self.get_invoice_status_code(obj)
		return {
			'1': 'Not Started',
			'2': 'In Process',
			'3': 'Finished',
		}.get(code, '')

	def _grn_line_item_is_fully_invoiced(self, li):
		inv_items = getattr(li, '_prefetched_objects_cache', {}).get('invoice_items') or li.invoice_items.all()
		return sum(float(inv.quantity) for inv in inv_items) >= float(li.quantity_received)

	def _grn_line_item_has_any_invoice(self, li):
		inv_items = getattr(li, '_prefetched_objects_cache', {}).get('invoice_items') or li.invoice_items.all()
		return bool(inv_items)

	class Meta:
		model = GoodsReceivedNote
		fields = [
			'grn_number', 'created', 'total_value_received', 'invoiced_quantity', 'invoice_status_code',
			'invoice_status_text', 'stores', 'purchase_order', 'grn_line_items'
		]