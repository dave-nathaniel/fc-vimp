# Configure django before running this script
# import os, django
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vimp.settings')
# django.setup()

import logging
from copy import deepcopy
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.contrib.auth import get_user_model
from icg_service.inventory import StockManagement
from egrn_service.models import GoodsReceivedNote
from egrn_service.serializers import GoodsReceivedNoteSerializer

logger = logging.getLogger()
users = get_user_model()

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
		"davynathaniel@gmail.com oguntoyeadebola21@gmail.com olawson@wajesmart.com posuala@wajesmart.com".split(" "),
	)
	email.content_subtype = 'html'
	return email.send()


def notify_approval_required(signable):
	'''
        Send an email notification to the users in the pending role who need to approve the given
        signable object. The workflow data is modified for more straightforward rendering.
    '''
	portal_url = 'https://vimp.foodconceptsplc.com'
	# Get the role of the current pending signatory
	current_pending_signatory = signable.get('workflow')['pending_approval_from']
	if not current_pending_signatory:
		return False
	# Get all users in the pending role
	users_in_pending_role = users.objects.filter(groups__name=current_pending_signatory)
	# If any user is found, proceed with sending the email notification.
	if users_in_pending_role:
		# Get the workflow data including the signatories and their roles.
		signatories = signable.get('workflow')['signatories']
		workflow = []
		for index, role in enumerate(signatories):
			# Do some modifications to the workflow data for more straightforward rendering
			role_signature = list(filter(lambda x: x['role'] == role, signable.get('workflow')['signatures']))
			signature_to_dict = dict(role_signature[0]) if role_signature else {'role': role}
			signature_to_dict.update({'level':index + 1})
			signature_to_dict.update({'signed':True if role_signature else False})
			signature_to_dict.update({'role_title':role.replace('_',' ').title()})
			workflow.append(signature_to_dict)
		# Render the HTML content of the template and send the email asynchronously
		html_content = render_to_string('approval_required.html', {
			'data': signable,
			'workflow': workflow,
			'portal_url': portal_url
		})
		# Get the email addresses of users in the pending role.
		user_emails = map(
			lambda user: user.email,
			users_in_pending_role
		)
		# Send the HTML content via email
		email = EmailMessage(
			f'Action Required on Invoice #{signable.get("id")}',
			html_content,
			'network@foodconceptsplc.com',
			user_emails,
		)
		email.content_subtype = 'html'
		return email.send()


if __name__ == "__main__":
	# from invoice_service.models import Invoice
	# from invoice_service.serializers import InvoiceSerializer
	# invoice = Invoice.objects.get(id=263)
	# notify_approval_required(InvoiceSerializer(invoice).data)
	...