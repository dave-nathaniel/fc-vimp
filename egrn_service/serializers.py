from datetime import datetime
from rest_framework import serializers
from .models import Surcharge, Store, GoodsReceivedNote, GoodsReceivedLineItem, PurchaseOrder, PurchaseOrderLineItem
from django.forms.models import model_to_dict


class SurchargeSerializer(serializers.ModelSerializer):
	class Meta:
		model = Surcharge
		fields = '__all__'


class StoreSerializer(serializers.ModelSerializer):
	
	def to_representation(self, instance):
		data = super().to_representation(instance)
		data.pop('metadata')
		return data
	
	class Meta:
		model = Store
		fields = '__all__'


class GoodsReceivedLineItemSerializer(serializers.ModelSerializer):
	# items description, unit price, product code and amount
	purchase_order_line_item = serializers.SerializerMethodField()
	grn_number = serializers.SerializerMethodField()
	tax_value = serializers.SerializerMethodField()
	metadata = serializers.JSONField()
	
	def get_purchase_order_line_item(self, obj):
		po_line_item = PurchaseOrderLineItemSerializer(obj.purchase_order_line_item, many=False).data
		po_line_item['ItemShipToLocation'] = po_line_item['metadata']['ItemShipToLocation']
		return po_line_item
	
	def get_grn_number(self, obj):
		return obj.grn.grn_number
	
	def get_tax_value(self, obj):
		return obj.gross_value_received - obj.net_value_received
	
	class Meta:
		model = GoodsReceivedLineItem
		fields = ['id', 'grn_number', 'quantity_received', 'gross_value_received', 'net_value_received','invoiced_quantity', 'is_invoiced', 'tax_value', 'metadata', 'date_received',
				  'purchase_order_line_item']


class PurchaseOrderLineItemSerializer(serializers.ModelSerializer):
	grn_line_items = GoodsReceivedLineItemSerializer(many=True, read_only=True, source="line_items")
	extra_fields = serializers.JSONField()
	# Delivery status code, text, outstanding quantity, delivered quantity, delivery completed
	delivery_status_code = serializers.SerializerMethodField()
	delivery_status_text = serializers.SerializerMethodField()
	delivery_outstanding_quantity = serializers.SerializerMethodField()
	delivered_quantity = serializers.FloatField()
	delivery_completed = serializers.SerializerMethodField()
	delivery_store = StoreSerializer(read_only=True)
	
	def get_delivery_outstanding_quantity(self, obj):
		# Calculate and return outstanding quantity
		return float(obj.quantity) - float(obj.delivered_quantity)
	
	def get_delivery_status_code(self, obj):
		return obj.delivery_status[0]
	
	def get_delivery_status_text(self, obj):
		return obj.delivery_status[1]
	
	def get_delivery_completed(self, obj):
		# Check if outstanding quantity is equal to the quantity
		return self.get_delivery_outstanding_quantity(obj) == 0
	
	class Meta:
		model = PurchaseOrderLineItem
		fields = ['object_id', 'delivery_store', 'product_name', 'unit_price', 'quantity', 'tax_rates', 'unit_of_measurement',
				  'delivery_status_code','delivery_status_text', 'delivered_quantity', 'delivery_outstanding_quantity',
				  'delivery_completed', 'extra_fields', 'metadata', 'grn_line_items']
		read_only_fields = ['delivery_store']


class PurchaseOrderSerializer(serializers.ModelSerializer):
	Item = PurchaseOrderLineItemSerializer(many=True, read_only=True, source='line_items')
	delivery_status_code = serializers.SerializerMethodField()
	delivery_status_text = serializers.SerializerMethodField()
	delivery_completed = serializers.SerializerMethodField()
	vendor = serializers.SerializerMethodField()
	
	def get_vendor(self, obj):
		return obj.vendor.byd_internal_id
	
	def get_delivery_status_code(self, obj):
		return obj.delivery_status[0]
	
	def get_delivery_status_text(self, obj):
		return obj.delivery_status[1]
	
	def get_delivery_completed(self, obj):
		return obj.delivery_status[0] == '3'
	
	def to_representation(self, instance):
		# Convert the datetime object to a date
		instance.date = instance.date.date() if isinstance(instance.date, datetime) else instance.date
		serialized = super().to_representation(instance)
		return serialized

	class Meta:
		model = PurchaseOrder
		fields = ['po_id', 'object_id', 'vendor', 'total_net_amount', 'date', 'delivery_status_code',
				  'delivery_status_text', 'delivery_completed', 'Item', 'metadata']


class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
	purchase_order = serializers.SerializerMethodField()
	grn_line_items = GoodsReceivedLineItemSerializer(many=True, read_only=True, source='line_items')
	total_value_received = serializers.FloatField(source='total_net_value_received')
	stores = StoreSerializer(many=True, read_only=True)
	
	def get_purchase_order(self, obj):
		po_dict = PurchaseOrderSerializer(obj.purchase_order, many=False).data
		po_dict["BuyerParty"], po_dict["Supplier"]= po_dict["metadata"]["BuyerParty"], po_dict["metadata"]["Supplier"]
		po_dict.pop('metadata')
		po_dict.pop('Item')
		return po_dict
	
	class Meta:
		model = GoodsReceivedNote
		fields = ['grn_number', 'created', 'total_value_received', 'invoiced_quantity', 'invoice_status_code',
				  'invoice_status_text', 'stores', 'purchase_order', 'grn_line_items']
		depth = 1
