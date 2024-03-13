from rest_framework import serializers
from .models import GoodsReceivedNote, GoodsReceivedLineItem

class GoodsReceivedLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoodsReceivedLineItem
        fields = ['id', 'grn', 'purchase_order_line_item', 'quantity_received']

class GoodsReceivedNoteSerializer(serializers.ModelSerializer):
    line_items = GoodsReceivedLineItemSerializer(many=True, read_only=True)

    class Meta:
        model = GoodsReceivedNote
        fields = ['id', 'purchase_order', 'store', 'grn_number', 'received_date', 'line_items']
