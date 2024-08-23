import logging
from copy import deepcopy
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from icg_service.inventory import StockManagement
from .models import GoodsReceivedNote
from .serializers import GoodsReceivedNoteSerializer

logger = logging.getLogger()

def post_to_icg(instance, ):
	'''
		Create a Purchase Order for the received good on ICG system for the purpose of updating the
		inventory with the received goods.
		TODO:
			- Confirm the purpose of the "costTotal" key.
			- Confirm the purpose of the "clientId" key.
	'''
	order_details = {
		"externalDocNo": str(instance.grn_number),
		"grossTotal": str(float(instance.total_gross_value_received)),
		"taxesTotal": str(float(instance.total_tax_value_received)),
		"netTotal": str(float(instance.total_net_value_received)),
		"costTotal": str(float(instance.total_net_value_received)),
		"clientId": "999901",
		"warehouse": str(instance.store.icg_warehouse_code),
		"orderDate": instance.created.strftime('%Y-%m-%d'),
	}
	order_items = [
		(lambda index, order_item: {
			"externalDocNo": str(instance.grn_number),
			"itemId": str(order_item.id),
			"barcode": str(order_item.purchase_order_line_item.metadata["ProductID"]),
			"description": str(order_item.purchase_order_line_item.metadata["Description"]),
			"totalQty": str(int(order_item.quantity_received)),
			"price": str(order_item.purchase_order_line_item.metadata["NetUnitPriceAmount"]),
			"cost": str(float(order_item.net_value_received)),
			"discount": "0",
			"totalPrice": str(float(order_item.net_value_received)),
			"line_No": str(index + 1),
			"date": order_item.date_received.strftime('%Y-%m-%d'),
		})(i, j) for i, j in enumerate(instance.line_items.all())
	]
	stock = StockManagement()
	# The posted_to_icg flag is set to True if the purchase order is successfully created on ICG
	instance.posted_to_icg = stock.create_purchase_order(order_details, order_items)
	return super(GoodsReceivedNote, instance).save() if instance.posted_to_icg else False


def send_grn_to_email(created_grn, ):
	# Serialize the GoodsReceivedNote instance along with its related GoodsReceivedLineItem instances
	goods_received_note = GoodsReceivedNoteSerializer(created_grn).data
	template_data = deepcopy(goods_received_note)
	# Modify some fields for more straightforward rendering
	template_data['purchase_order']['BuyerParty']['BuyerPartyName'] = template_data['purchase_order']['BuyerParty']['BuyerPartyName'][0]
	template_data['purchase_order']['Supplier']['SupplierName'] = template_data['purchase_order']['Supplier']['SupplierName'][0]
	template_data['purchase_order']['Supplier']['SupplierPostalAddress'] = template_data['purchase_order']['Supplier']['SupplierPostalAddress'][0]
	# Render the HTML content of the template and send the email asynchronously
	html_content = render_to_string('grn_receipt_template.html', {'data': template_data})
	# Send the HTML content via email
	email = EmailMessage(
		'Your Goods Received Note',
		html_content,
		'network@foodconceptsplc.com',
		['davynathaniel@gmail.com']#, 'oguntoyeadebola21@gmail.com']
	)
	email.content_subtype = 'html'
	return email.send()