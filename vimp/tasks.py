import os
# Uncomment the next 3 lines to configure django for running this script as an independent module.
# import django
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vimp.settings')
# django.setup()

import logging
import random
import string
from pprint import pprint
from copy import deepcopy
from dotenv import load_dotenv
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user_model

from core_service.services import send_sms
from icg_service.inventory import StockManagement
from egrn_service.models import GoodsReceivedNote
from invoice_service.models import Invoice
from egrn_service.serializers import GoodsReceivedNoteSerializer, GoodsReceivedLineItemSerializer

import byd_service.rest as byd_rest
import byd_service.util as byd_util
from byd_service.models import ByDPostingStatus, get_or_create_byd_posting_status
from django.contrib.contenttypes.models import ContentType

load_dotenv()

logger = logging.getLogger()
users = get_user_model()

def post_to_icg(instance, ):
	'''
		Create a Purchase Order for the received good on ICG system for the purpose of updating the
		inventory with the received goods.
		Although it should not be, we anticipate a situation where one GRN serves multiple stores.
		TODO:
			- Confirm the purpose of the "costTotal" key.
			- Confirm the purpose of the "clientId" key.
	'''
	# If multiple stores are involved, modify the GRN number by appending an alphabet at the end.
	# This is because ICG will throw an error if there are multiple posting with the same 'externalDocNo'.
	def get_ref_mod(store_count):
		# If there is only one store, there is no need to append an alphabet.
		if store_count < 2:
			return lambda x: ''
		return lambda x: str(chr(x + 65))
	# Get the function to get the reference modification for the current store.
	ref_mod = get_ref_mod(len(instance.stores))
	# Dictionary to hold the posting status of each store.
	posted_status = {}
	
	# Iterate over the stores involved in the GRN.
	for index, store in enumerate(instance.stores):
		# Get only the line items that belong to this store.
		items_for_store = instance.line_items.filter(purchase_order_line_item__delivery_store=store)
		# Modify the GRN number by appending an alphabet, if necessary.
		externalDocNo = f'{str(instance.grn_number)}{ref_mod(index)}'
		# Recalculate the grossTotal, netTotal, and taxesTotal for this store.
		grossTotal = float(sum([item.gross_value_received for item in items_for_store]))
		netTotal = float(sum([item.net_value_received for item in items_for_store]))
		taxesTotal = float(grossTotal - netTotal)
		order_details = {
			"externalDocNo": externalDocNo,
			"grossTotal": str(grossTotal),
			"taxesTotal": str(taxesTotal),
			"netTotal": str(netTotal),
			"costTotal": str(netTotal),
			"clientId": "999901",
			"warehouse": str(store.icg_warehouse_code),
			"orderDate": instance.created.strftime('%Y-%m-%d'),
		}
		order_items = [
			(lambda index, order_item: {
				"externalDocNo": externalDocNo,
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
			})(i, j) for i, j in enumerate(items_for_store)
		]
		# The posted_to_icg flag is set to True if the purchase order is successfully created on ICG
		stock = StockManagement()
		is_posted = stock.create_purchase_order(order_details, order_items)
		# Save the posting status of the items for the current store.
		items_for_store.update(posted_to_icg=is_posted)
		# Append the posting status to our reporting dictionary.
		posted_status[store.store_name] = is_posted
	# return the dictionary of posting statuses and a boolean indicating whether all items were posted successfully.
	return posted_status, all(posted_status.values())


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


def post_to_gl(args):
	import app_settings.models as app_settings
	from byd_service import gl_posting
	# Get the data from the provided arguments
	grn = args.get('grn') # GoodsReceivedNote instance
	action = args.get('action') # The action that triggered the GL posting (either 'receipt' or 'invoice_approval')
	# List to hold the posting status of each line item to GL.
	posting_status = []
	# The line items to post to GL
	line_items = GoodsReceivedLineItemSerializer(grn.line_items, many=True).data
	# Iterate over the line items and perform the GL entry based on the retrieved GL entry definition.
	for line_item in line_items:
		# Get the product metadata and product category from the line item.
		product_metadata = line_item.get('purchase_order_line_item', {}).get('metadata')
		product_category = product_metadata.get('ProductCategoryInternalID')
		# Get the GL entry definition based on the product category and the action.
		gl_entry_definition = (app_settings.ProductCategoryGLEntry.objects
							   .filter(product_category_id=product_category)
							   .filter(action=action).first())
		# Definitions for debit and credit states.
		definitions = {
			"D": gl_entry_definition.debit_states.all(),
			"C": gl_entry_definition.credit_states.all(),
		}
		# Format the GL entries based on the retrieved GL entry definitions.
		entries = []
		for indicator in definitions.keys():
			# Append the GL entries to the entries list based on the debit or credit states.
			entries = entries + [
				gl_posting.format_entry(
					indicator,
					product_metadata.get('ItemShipToLocation', {}).get('LocationID'),
					item.gl_account.account_code,
					float(line_item.get(item.transaction_value_field, 0))
				) for item in definitions[indicator]
			]
		# Format date in YYYY-MM-DD format
		date_received = line_item.get('date_received', '')
		# Post the GL entries and append the posting status to the list.
		posting_status.append(
			gl_posting.post_to_byd(date_received, entries)
		)
	# Return a boolean indicating whether all line items were posted successfully to GL.
	return all(posting_status)


def create_grn_on_byd(grn: GoodsReceivedNote):
	# Initialize the REST client
	rest_client = byd_rest.RESTServices()
	payload = {
		"GSR_Integration_KUT": "YES",
		"Item": [
			{
				"ProductID": line_item.purchase_order_line_item.product_id,
				"DeliveredQuantity": str(float(line_item.quantity_received)),
				"DeliveredQuantityUnitCode": line_item.purchase_order_line_item.metadata["QuantityUnitCode"],
				"DeliveryStartDateTime": f"{byd_util.format_datetime_to_iso8601(line_item.date_received)}Z",
				"DeliveryEndDateTime": f"{byd_util.format_datetime_to_iso8601(line_item.date_received)}Z",
				"ItemPurchaseOrderReference": [
					{
						"ID": str(line_item.purchase_order_line_item.purchase_order.po_id),
						"ItemID": line_item.purchase_order_line_item.metadata["ID"],
						"ItemTypeCode": line_item.purchase_order_line_item.metadata["ItemTypeCode"],
					}
				],
			} for line_item in grn.line_items.all()
		]
	}
	
	status = get_or_create_byd_posting_status(grn, request_payload=payload, task_name='vimp.tasks.create_grn_on_byd')
	
	try:
		response = rest_client.create_grn(payload)
		# Get the object ID from the response and post the GRN
		try:
			object_id = response.get("d", {}).get("results", {}).get("ObjectID")
			response = rest_client.post_grn(object_id)
		except Exception as e:
			raise Exception(f"Error posting GRN {grn.grn_number}: {e}")
		# Mark as success
		status.mark_success(
			response.get("d", {})
			.get("results", {})
		)
	except Exception as e:
		logging.error(f"Error creating GRN {grn.grn_number}: {e}")
		# Mark as failure
		status.mark_failure(e)
		# Increment retry count
		status.increment_retry()
		return False
	return True


def create_invoice_on_byd(invoice: Invoice):
	# Initialize the REST client
	rest_client = byd_rest.RESTServices()
	payload = {
		"Inv_Integration_KUT": "YES",
		"TypeCode": "004",
		"DataOriginTypeCode": "1",
		"ItemsGrossAmountIndicator": True,
		"InvoiceDescription": invoice.description,
		"InvoiceDate": byd_util.format_datetime_to_iso8601(invoice.date_created),
		"ExternalReference": {
			"BusinessTransactionDocumentRelationshipRoleCode": "7",
			"ID": str(invoice.external_document_id),
			"TypeCode": "28",
		},
		"SellerParty": {
			"PartyID": invoice.purchase_order.vendor.byd_internal_id,
		},
		"Item": [
			{
				"TypeCode": "002",
				"ProductID": str(line_item.po_line_item.product_id),
				"ProductTypeCode": "2",
				"Quantity": str(float(line_item.quantity)),
				"QuantityUnitCode": line_item.po_line_item.metadata["QuantityUnitCode"],
				"GrossUnitPriceAmount": str(float(line_item.po_line_item.unit_price)),
				"GrossUnitPriceBaseQuantity": "1",
				"ItemPurchaseOrderReference": {
					"ID": str(line_item.po_line_item.purchase_order.po_id),
					"ItemID": str(line_item.po_line_item.metadata["ID"]),
				},
			}
			for line_item in invoice.invoice_line_items.all()
		]
	}
	
	status = get_or_create_byd_posting_status(invoice, request_payload=payload, task_name='vimp.tasks.create_invoice_on_byd')
	
	try:
		response = rest_client.create_supplier_invoice(payload)# Mark as success
		# Get the object ID from the response and post the GRN
		try:
			object_id = response.get("d", {}).get("results", {}).get("ObjectID")
			response = rest_client.post_invoice(object_id)
		except Exception as e:
			raise Exception(f"Error posting Invoice: {e}")
		# Mark as success
		status.mark_success(
			response.get("d", {})
			.get("results", {})
		)
	except Exception as e:
		logging.error(f"Error creating Invoice {invoice.id}: {e}")
		# Mark as failure
		status.mark_failure(e)
		# Increment retry count
		status.increment_retry()
		return False
	return True
	

def create_inbound_delivery_notification_on_byd(grn: GoodsReceivedNote):
	# Initialize the REST client
	rest_client = byd_rest.RESTServices()
	# Generate the notification ID by combining the GRN number two random alphabets
	notification_id = f"{grn.grn_number}{''.join(random.choices(string.ascii_uppercase, k=2))}"
	payload = {
		"ID": notification_id,
		"ProcessingTypeCode": "SD",
		"Item": [
			{
				"ID": line_item.purchase_order_line_item.metadata["ID"],
				"TypeCode": "14",
				"ProductID": line_item.purchase_order_line_item.product_id,
				"ItemDeliveryQuantity":{
					"Quantity": str(float(line_item.quantity_received)),
					"UnitCode": line_item.purchase_order_line_item.metadata["QuantityUnitCode"],
				},
				"ItemPurchaseOrderReference": {
					"ID": str(line_item.purchase_order_line_item.purchase_order.po_id),
					"ItemID": line_item.purchase_order_line_item.metadata["ID"],
					"ItemTypeCode": line_item.purchase_order_line_item.metadata["ItemTypeCode"],
					"RelationshipRoleCode": "1"
				},
				"ItemSellerParty": {
					"PartyID": line_item.grn.purchase_order.vendor.byd_internal_id
				},
				"ItemInboundDeliveryRequestReference": {
					"ID": notification_id,
					"ItemID": line_item.purchase_order_line_item.metadata["ID"],
					"ItemTypeCode": "14",
					"TypeCode": "59",
					"RelationshipRoleCode": "1"
				}
			} for line_item in grn.line_items.all()
		],
		"SenderParty":{
			"PartyID": grn.purchase_order.vendor.byd_internal_id
		},
		"ShipToParty": {
			# TODO: Make this configuration dynamic
			"PartyID": "FC-0001"
		}
	}
	
	status = get_or_create_byd_posting_status(grn, request_payload=payload, task_name='vimp.tasks.create_inbound_delivery_notification_on_byd')
	
	try:
		response = rest_client.create_inbound_delivery_notification(payload)
		# Get the object ID from the response and post the GRN
		try:
			object_id = response.get("d", {}).get("results", {}).get("ObjectID")
			response = rest_client.post_delivery_notification(object_id)
		except Exception as e:
			raise Exception(f"Error posting GRN {grn.grn_number}: {e}")
		# Mark as success
		status.mark_success(
			response.get("d", {})
			.get("results", {})
		)
	except Exception as e:
		logging.error(f"Error creating GRN {grn.grn_number}: {e}")
		# Mark as failure
		status.mark_failure(e)
		# Increment retry count
		status.increment_retry()
		return False
	return True
	

def notify_approval_required(signable):
	'''
		Send an email notification to the users in the pending role who need to approve the given
		signable object. The workflow data is modified for more straightforward rendering.
	'''
	portal_url = 'https://vimp.foodconceptsplc.com/approval'
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
	

def send_otp_to_user(args):
	from core_service.models import VendorProfile
	otp = args.get('otp')
	request = args.get('request')
	user = args.get('user')
	if user.email:
		user_emails = os.getenv("TEST_EMAILS").split(" ") + [user.email]
		html_content = render_to_string('otp.html', {
			'otp': otp,
			'request': request
		})
		# Send the HTML content via email
		email = EmailMessage(
			f'Your Vendor Verification Code',
			html_content,
			'network@foodconceptsplc.com',
			user_emails,
		)
		email.content_subtype = 'html'
		email.send()
	try:
		vendor_profile = user.vendor_profile
		if vendor_profile.phone:
			vendor_phone = vendor_profile.phone.replace(" ", "").zfill(11)
			phone_numbers = os.getenv("TEST_PHONES").split(" ") + [vendor_phone]
			phone_numbers = [number.zfill(11) for number in phone_numbers]
			send_sms(phone_numbers, os.getenv("SMS_FROM"), f"Your Food Concepts Vendor login OTP code is {otp}.")
	except ObjectDoesNotExist:
		pass
	return True


def send_reset_link_to_user(args):
	user = args.get('user')
	token = args.get('token')
	if user.email:
		user_emails = os.getenv("TEST_EMAILS").split(" ") + [user.email]
		html_content = render_to_string('password_reset.html', {
			'reset_link': f"{os.getenv('DEV_HOST')}/reset_password?token={token}&email={user.email}",
		})
		# Send the HTML content via email
		email = EmailMessage(
			f'Password Reset Request',
			html_content,
			'network@foodconceptsplc.com',
			user_emails,
		)
		email.content_subtype = 'html'
		email.send()
		return True


def send_vendor_setup_email(args):
	instance, id_hash = args.get('instance'), args.get('id_hash')
	sender_name = os.getenv("MESSAGE_FROM")
	email_from = os.getenv("EMAIL_USER")
	merchant_name = str(instance.byd_metadata["BusinessPartner"]["BusinessPartnerFormattedName"])
	email_to = instance.identifier.strip().split(" ")
	# email_to = "davynathaniel@gmail.com".split(" ")
	email_subject = f"Complete your account setup"
	
	verification_link = f'{os.getenv("DEV_HOST")}/sign-up?{id_hash}={instance.token}'
	
	content = render_to_string('verification_setup.html', {
		"MERCHANT_NAME": merchant_name,
		"LINK": verification_link,
	})
	
	email = EmailMessage(
		subject=email_subject,
		body=content,
		from_email=f"{sender_name} <{email_from}>",
		to=email_to
	)
	
	email.content_subtype = 'html'
	
	try:
		email.send()
		return True
	except Exception as e:
		logging.error(f"An error occurred sending an email: {e}")
		return False


if __name__ == "__main__":
	# egrn = GoodsReceivedNote.objects.get(id=1318)
	# print(create_inbound_delivery_notification_on_byd(egrn))
	# invoice = Invoice.objects.get(id=323)
	# print(create_invoice_on_byd(invoice))
	...