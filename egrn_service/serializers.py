from rest_framework import serializers
from .models import GoodsReceivedNote, GoodsReceivedLineItem, PurchaseOrder, PurchaseOrderLineItem
from django.db.models import Sum
from django.forms.models import model_to_dict

class GoodsReceivedLineItemSerializer(serializers.ModelSerializer):
	#items description, unit price, product code and amount
	purchase_order = serializers.SerializerMethodField()
	def get_purchase_order(self, obj):
		po_model = obj.purchase_order_line_item
		po_line_item = model_to_dict(po_model)
		po_line_item.pop("metadata")
		return  po_line_item
	
	class Meta:
		model = GoodsReceivedLineItem
		fields = ['id', 'grn', 'quantity_received', 'purchase_order']

class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
	line_items = GoodsReceivedLineItemSerializer(many=True, read_only=True)
	# purchase_order = serializers.SerializerMethodField()
	#
	# def get_purchase_order(self, obj):
	# 	return obj.purchase_order
	
	class Meta:
		model = GoodsReceivedNote
		fields = ['id', 'purchase_order', 'store', 'grn_number', 'received_date', 'line_items']

class PurchaseOrderLineItemSerializer(serializers.ModelSerializer):
	grn_line_item = GoodsReceivedLineItemSerializer(many=True, read_only=True)
	outstanding_quantity = serializers.SerializerMethodField()
	completed_delivery = serializers.SerializerMethodField()
	
	def get_outstanding_quantity(self, obj):
		# Access related GoodsReceivedLineItem instances and calculate total received quantity
		total_received_quantity = obj.grn_line_item.aggregate(total_received=Sum('quantity_received'))['total_received']
		if total_received_quantity is None:
			total_received_quantity = 0
		# Calculate and return outstanding quantity
		return obj.quantity - total_received_quantity
	
	def get_completed_delivery(self, obj):
		# Check if outstanding quantity is equal to the quantity
		return self.get_outstanding_quantity(obj) == 0
	
	class Meta:
		model = PurchaseOrderLineItem
		fields = ['object_id', 'product_name', 'quantity', 'unit_price', 'outstanding_quantity', 'completed_delivery', 'grn_line_item']

class PurchaseOrderSerializer(serializers.ModelSerializer):
	Item = PurchaseOrderLineItemSerializer(many=True, read_only=True, source='line_items')
	completed_delivery = serializers.SerializerMethodField()
	vendor = serializers.SerializerMethodField()
	
	def get_completed_delivery(self, obj):
		# Retrieve all related PurchaseOrderLineItems
		line_items = obj.line_items.all()
		# Check if all PurchaseOrderLineItems are completed
		for line_item in line_items:
			total_received_quantity = line_item.grn_line_item.aggregate(total_received=Sum('quantity_received'))[
				'total_received']
			if total_received_quantity is None:
				total_received_quantity = 0
			if line_item.quantity - total_received_quantity != 0:
				return False
		return True
	
	def get_vendor(self, obj):
		return obj.vendor.byd_internal_id
	
	class Meta:
		model = PurchaseOrder
		fields = ['id', 'vendor', 'object_id', 'po_id', 'total_net_amount', 'total_gross_amount', 'date', 'completed_delivery', 'Item']