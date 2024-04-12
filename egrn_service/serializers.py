from rest_framework import serializers
from .models import GoodsReceivedNote, GoodsReceivedLineItem, PurchaseOrder, PurchaseOrderLineItem
from django.db.models import Sum
from django.forms.models import model_to_dict
from byd_service.rest import RESTServices


class GoodsReceivedLineItemSerializer(serializers.ModelSerializer):
	# items description, unit price, product code and amount
	purchase_order_line_item = serializers.SerializerMethodField()
	grn_number = serializers.SerializerMethodField()
	
	def get_purchase_order_line_item(self, obj):
		po_line_item = model_to_dict(obj.purchase_order_line_item)
		po_line_item.pop('metadata')
		return po_line_item
	
	def get_grn_number(self, obj):
		return obj.grn.grn_number
	
	class Meta:
		model = GoodsReceivedLineItem
		fields = ['id', 'grn_number', 'quantity_received', 'date_received', 'purchase_order_line_item']


class PurchaseOrderLineItemSerializer(serializers.ModelSerializer):
	grn_line_items = serializers.SerializerMethodField()
	outstanding_quantity = serializers.SerializerMethodField()
	delivery_status_code = serializers.SerializerMethodField()
	delivery_status_text = serializers.SerializerMethodField()
	delivered_quantity = serializers.SerializerMethodField()
	delivery_completed = serializers.SerializerMethodField()
	
	# get delivered quantity
	def get_delivered_quantity(self, obj):
		return obj.delivered_quantity
	
	def get_outstanding_quantity(self, obj):
		# Calculate and return outstanding quantity
		return float(obj.quantity) - float(obj.delivered_quantity)
	
	def get_delivery_status_code(self, obj):
		return obj.delivery_status[0]
	
	def get_delivery_status_text(self, obj):
		return obj.delivery_status[1]
	
	def get_delivery_completed(self, obj):
		# Check if outstanding quantity is equal to the quantity
		return self.get_outstanding_quantity(obj) == 0
	
	def get_grn_line_items(self, obj):
		# return the grn_line_items using model_to_dict
		all_grn_line_items = obj.grn_line_item.all()
		grn_line_items_serializer = GoodsReceivedLineItemSerializer(all_grn_line_items, many=True).data
		without_the_po_line_item = [item.pop('purchase_order_line_item') for item in grn_line_items_serializer]
		return grn_line_items_serializer
	
	class Meta:
		model = PurchaseOrderLineItem
		fields = ['object_id', 'product_name', 'unit_price', 'quantity', 'unit_of_measurement', 'delivery_status_code',
		          'delivery_status_text', 'delivered_quantity', 'outstanding_quantity', 'delivery_completed',
		          'metadata', 'grn_line_items']


class PurchaseOrderSerializer(serializers.ModelSerializer):
	Item = PurchaseOrderLineItemSerializer(many=True, read_only=True, source='line_items')
	delivery_status_code = serializers.SerializerMethodField()
	delivery_status_text = serializers.SerializerMethodField()
	delivery_completed = serializers.SerializerMethodField()
	vendor = serializers.SerializerMethodField()
	
	def get_vendor(self, obj):
		# vendor = byd_rest_services.get_vendor_by_id(obj.vendor.byd_internal_id, id_type=query_param[1])
		return obj.vendor.byd_internal_id
	
	def get_delivery_status_code(self, obj):
		return obj.delivery_status[0]
	
	def get_delivery_status_text(self, obj):
		return obj.delivery_status[1]
	
	def get_delivery_completed(self, obj):
		return obj.delivery_status[0] == 3
	
	class Meta:
		model = PurchaseOrder
		fields = ['po_id', 'object_id', 'vendor', 'total_net_amount', 'date', 'delivery_status_code',
		          'delivery_status_text', 'delivery_completed', 'Item', 'metadata']


class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
	purchase_order = serializers.SerializerMethodField()
	line_items = GoodsReceivedLineItemSerializer(many=True, read_only=True)
	
	def get_purchase_order(self, obj):
		po_dict = PurchaseOrderSerializer(obj.purchase_order, many=False).data
		po_dict.pop('metadata')
		po_dict.pop('Item')
		return po_dict
	
	class Meta:
		model = GoodsReceivedNote
		fields = ['grn_number', 'store', 'created', 'purchase_order', 'line_items']
