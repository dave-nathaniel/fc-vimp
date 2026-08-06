import os
# Uncomment the next 3 lines to configure django for running this script as an independent module.
# import django
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vimp.settings')
# django.setup()

import logging
import uuid
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
from byd_service.models import get_or_create_byd_posting_status

import time
from datetime import timedelta
from django.utils import timezone
from django_q.tasks import schedule
from django_q.models import Schedule

load_dotenv()

logger = logging.getLogger()
users = get_user_model()

# Maximum number of automatic lock-conflict retries before a posting is left failed.
MAX_BYD_RETRIES = 6


def _schedule_byd_lock_retry(func_path: str, object_id: int, retry_count: int, label: str):
	"""
		Schedule a single future re-run of a ByD posting task using exponential
		backoff with jitter. Used when a posting fails due to an object lock so the
		retry waits for the lock to clear instead of immediately dog-piling.
	"""
	delay = byd_util.compute_backoff_seconds(retry_count)
	# UUID suffix guarantees a unique schedule name even when many tasks fail in the
	# same second under lock contention (avoids any name collision on the Schedule row).
	schedule(
		func_path,
		object_id,
		schedule_type=Schedule.ONCE,
		next_run=timezone.now() + timedelta(seconds=delay),
		name=f"{label}-lock-retry-{retry_count}-{uuid.uuid4().hex[:8]}",
	)
	logger.warning(f"{label}: ByD object locked. Scheduled retry #{retry_count} in {delay}s.")

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
	# Set the emails to receive this GRN
	recepient_emails = list(set([item.purchase_order_line_item.delivery_store.store_email for item in created_grn.line_items.all()]))
	# Try to add the vendor's email if a user profile exists for the vendor
	try:
		recepient_emails.append(created_grn.purchase_order.vendor.user.email)
	except Exception as e:
		pass
	recepient_emails.append(os.getenv('TEST_EMAILS'))
	# Send the HTML content via email
	email = EmailMessage(
		'Your Goods Received Note',
		html_content,
		'network@foodconceptsplc.com',
		recepient_emails
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
	# Allow being called with either a GRN instance (initial dispatch) or its id (scheduled retry).
	if isinstance(grn, int):
		grn = GoodsReceivedNote.objects.get(id=grn)
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
	po_id = grn.purchase_order.po_id

	# Idempotency guard: see create_inbound_delivery_notification_on_byd.
	if status.status == 'success':
		logger.info(f"GRN {grn.grn_number}: GSA already posted to ByD; skipping.")
		return True

	try:
		# Serialise writes per purchase order so concurrent workers don't lock each other out.
		with byd_util.po_write_lock(po_id) as acquired:
			if not acquired:
				raise byd_util.ByDObjectLockedError(
					f"PO {po_id} is being posted by another worker; deferring GRN {grn.grn_number}."
				)
			# Resume support: don't create a second GSA if a prior attempt already did.
			object_id = (status.response_data or {}).get("ObjectID")
			if not object_id:
				response = rest_client.create_grn(payload)
				object_id = response.get("d", {}).get("results", {}).get("ObjectID")
				if not object_id:
					raise ValueError(f"ByD did not return an ObjectID for GRN {grn.grn_number}.")
				# Persist BEFORE posting so a failed post resumes instead of re-creating.
				status.response_data = {"ObjectID": object_id, "stage": "created"}
				status.save(update_fields=['response_data', 'updated_at'])
			# Post the GRN
			try:
				rest_client.post_grn(object_id)
			except Exception as e:
				raise Exception(f"Error posting GRN {grn.grn_number}: {e}")
			# Mark as success
			status.mark_success({"ObjectID": object_id, "stage": "posted"})
		return True
	except Exception as e:
		logging.error(f"Error creating GRN {grn.grn_number}: {e}")
		# Mark as failure
		status.mark_failure(str(e))
		# Increment retry count
		status.increment_retry()
		# If the failure is a ByD object lock, schedule a backoff retry (until capped).
		if byd_util.is_byd_lock_error(e) and status.retry_count <= MAX_BYD_RETRIES:
			_schedule_byd_lock_retry(
				'vimp.tasks.create_grn_on_byd',
				grn.id, status.retry_count, f'Create-GRN-{grn.grn_number}'
			)
		return False


def handle_delivery_notification_result(task):
	"""
		Log the result of a delivery notification task. Lock-conflict retries are
		owned by the task itself (backoff via _schedule_byd_lock_retry), so this
		hook no longer re-queues to avoid duplicate concurrent attempts.
	"""
	if task.success:
		logger.info(f"Delivery notification task completed successfully: {task.id}")
	else:
		logger.error(f"Delivery notification task failed: {task.id}, Error: {task.result}")

def handle_invoice_result(task):
	"""
		Log the result of an invoice task. Lock-conflict retries are owned by the
		task itself (backoff via _schedule_byd_lock_retry), so this hook no longer
		re-queues to avoid duplicate concurrent attempts.
	"""
	if task.success:
		logger.info(f"Invoice task completed successfully: {task.id}")
	else:
		logger.error(f"Invoice task failed: {task.id}, Error: {task.result}")

def create_inbound_delivery_notification_on_byd(grn: GoodsReceivedNote):
	# Allow being called with either a GRN instance (initial dispatch) or its id (scheduled retry).
	if isinstance(grn, int):
		grn = GoodsReceivedNote.objects.get(id=grn)
	# Initialize the REST client
	rest_client = byd_rest.RESTServices()

	# The ByD-facing document ID is derived from the GRN number alone — no random
	# component — so every attempt for this GRN presents the SAME external ID, and a
	# re-send is recognisable in ByD as a duplicate instead of being accepted as a
	# new document. GRNs already mid-flight keep their stored (legacy, random-
	# suffixed) ID so retries stay consistent with what ByD already holds.
	notification_id = grn.inbound_delivery_notification_id or str(grn.grn_number)
	
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
	po_id = grn.purchase_order.po_id

	# Idempotency guard: stale scheduled retries, admin re-dispatches and broker
	# re-deliveries all re-enter this function. If a previous attempt already
	# completed there is nothing to do — re-running would duplicate the document.
	if status.status == 'success':
		logger.info(f"GRN {grn.grn_number}: delivery notification already posted to ByD; skipping.")
		return True
	if grn.is_nullified:
		logger.warning(f"GRN {grn.grn_number} is nullified; not posting a delivery notification.")
		return False

	try:
		# Serialise writes per purchase order so concurrent workers don't lock each other out.
		with byd_util.po_write_lock(po_id) as acquired:
			if not acquired:
				raise byd_util.ByDObjectLockedError(
					f"PO {po_id} is being posted by another worker; deferring GRN {grn.grn_number}."
				)
			# Resume support: only create the document if no prior attempt did. The
			# ObjectID is persisted BEFORE the posting step, so a retry after a failed
			# post lands here and skips straight to posting — retrying used to re-run
			# the create as well, which is exactly what produced duplicate documents.
			object_id = grn.inbound_delivery_object_id
			already_posted = bool((grn.inbound_delivery_metadata or {}).get("post_response"))
			if not object_id:
				# A previous attempt may have created the document without us ever
				# seeing the response (worker killed / connection dropped mid-call).
				# The deterministic ID makes that recoverable by lookup.
				existing = rest_client.get_inbound_delivery_by_external_id(notification_id)
				if existing:
					object_id = existing.get("ObjectID")
					# ReleaseStatusCode '3' == Released: it was already posted too.
					already_posted = str(existing.get("ReleaseStatusCode", "")) == "3"
					create_response = {"recovered_from_lookup": True, "ObjectID": object_id}
				else:
					# Create the notification
					response = rest_client.create_inbound_delivery_notification(payload)
					object_id = response.get("d", {}).get("results", {}).get("ObjectID")
					create_response = response
				if not object_id:
					raise ValueError(
						f"ByD did not return an ObjectID for delivery notification {notification_id}."
					)

				grn.inbound_delivery_object_id = object_id
				grn.inbound_delivery_notification_id = notification_id
				grn.inbound_delivery_metadata = {
					"payload": payload,
					"create_response": create_response
				}
				grn.save(update_fields=[
					'inbound_delivery_object_id',
					'inbound_delivery_notification_id',
					'inbound_delivery_metadata'
				])

				# Add a delay before posting
				time.sleep(5)

			if not already_posted:
				# Post the notification
				post_response = rest_client.post_delivery_notification(object_id)
				grn.inbound_delivery_metadata.update({
					"post_response": post_response,
				})
				grn.save(update_fields=['inbound_delivery_metadata'])

			# Mark as success
			status.mark_success({
				"ObjectID": object_id,
				"ID": notification_id,
			})
		return True

	except Exception as e:
		logger.error(f"Error creating GRN {grn.grn_number}: {e}")
		# Mark as failure
		status.mark_failure(str(e))
		# Increment retry count
		status.increment_retry()
		
		# If the failure is a ByD object lock, schedule a backoff retry (until capped).
		if byd_util.is_byd_lock_error(e) and status.retry_count <= MAX_BYD_RETRIES:
			_schedule_byd_lock_retry(
				'vimp.tasks.create_inbound_delivery_notification_on_byd',
				grn.id, status.retry_count, f'Create-Inbound-Notif-{grn.grn_number}'
			)
		return False

def _get_invoice_description(invoice: Invoice) -> str:
	first_signature = invoice.get_signatures().last()
	if first_signature and first_signature.comment:
		return first_signature.comment[:40]
	return f"{invoice.purchase_order.vendor.user.first_name.title()} for {invoice.purchase_order}"[:40]


def create_invoice_on_byd(invoice: Invoice):
	# Allow being called with either an Invoice instance (initial dispatch) or its id (scheduled retry).
	if isinstance(invoice, int):
		invoice = Invoice.objects.get(id=invoice)
	# Initialize the REST client
	rest_client = byd_rest.RESTServices()
		
	payload = {
		"Inv_Integration_KUT": "YES",
		"TypeCode": "004",
		"DataOriginTypeCode": "1",
		"ItemsGrossAmountIndicator": True,
		"InvoiceDescription": _get_invoice_description(invoice),
		"InvoiceDate": byd_util.format_datetime_to_iso8601(invoice.date_created),
		"ExternalReference": {
			"BusinessTransactionDocumentRelationshipRoleCode": "7",
			"ID": str(invoice.external_document_id) if invoice.external_document_id else f'{invoice.purchase_order.vendor.byd_internal_id}-{invoice.id}',
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
	po_id = invoice.purchase_order.po_id

	# Idempotency guard: see create_inbound_delivery_notification_on_byd.
	if status.status == 'success':
		logger.info(f"Invoice {invoice.id}: already posted to ByD; skipping.")
		return True

	try:
		# Serialise writes per purchase order so an invoice and a delivery posting for the
		# same PO don't run concurrently and lock each other out in ByD.
		with byd_util.po_write_lock(po_id) as acquired:
			if not acquired:
				raise byd_util.ByDObjectLockedError(
					f"PO {po_id} is being posted by another worker; deferring invoice {invoice.id}."
				)
			# Resume support: a previous attempt may have created the ByD invoice and
			# failed at the posting step. Its ObjectID was persisted on the status row
			# (mark_failure leaves response_data untouched), so don't create it again.
			object_id = (status.response_data or {}).get("ObjectID")
			if not object_id:
				# Create the invoice
				response = rest_client.create_supplier_invoice(payload)
				object_id = response.get("d", {}).get("results", {}).get("ObjectID")
				if not object_id:
					raise ValueError(f"ByD did not return an ObjectID for invoice {invoice.id}.")
				# Persist BEFORE posting so a failed post resumes instead of re-creating.
				status.response_data = {"ObjectID": object_id, "stage": "created"}
				status.save(update_fields=['response_data', 'updated_at'])

				# Add a delay before posting
				time.sleep(5)

			# Post the invoice
			rest_client.post_invoice(object_id)

			# Mark as success
			status.mark_success({"ObjectID": object_id, "stage": "posted"})
		return True

	except Exception as e:
		logger.error(f"Error creating Invoice {invoice.id}: {e}")
		# Mark as failure
		status.mark_failure(str(e))
		# Increment retry count
		status.increment_retry()
		
		# If the failure is a ByD object lock, schedule a backoff retry (until capped).
		if byd_util.is_byd_lock_error(e) and status.retry_count <= MAX_BYD_RETRIES:
			_schedule_byd_lock_retry(
				'vimp.tasks.create_invoice_on_byd',
				invoice.id, status.retry_count, f'Create-Invoice-{invoice.id}'
			)
		return False


def notify_approval_required(signable):
	'''
		Send an email notification to the users in the pending role who need to approve the given
		signable object. The workflow data is modified for more straightforward rendering.
	'''
	portal_url = f'{os.getenv("VIMP_HOST")}/approval'
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
		user_emails = [user.email]
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


def cancel_inbound_delivery_notification_on_byd(grn_id: int, cancel_payload: dict):
	rest_client = byd_rest.RESTServices()
	grn = GoodsReceivedNote.objects.get(id=grn_id)
	status = get_or_create_byd_posting_status(
		grn,
		request_payload=cancel_payload,
		task_name='vimp.tasks.cancel_inbound_delivery_notification_on_byd'
	)

	# Idempotency guards: a re-queued cancellation (admin re-click, duplicate
	# dispatch) must not post a second negative-quantity document.
	if grn.is_nullified:
		logger.info(f"GRN {grn.grn_number} is already nullified; skipping cancellation.")
		return True
	if status.status == 'success':
		# The cancellation reached ByD but the local bookkeeping was interrupted.
		grn.mark_nullified(reason="Admin-triggered nullification")
		return True

	po_id = grn.purchase_order.po_id

	try:
		# Serialise against any concurrent create/post for the same PO.
		with byd_util.po_write_lock(po_id) as acquired:
			if not acquired:
				raise byd_util.ByDObjectLockedError(
					f"PO {po_id} is being posted by another worker; cannot cancel GRN {grn.grn_number} yet."
				)
			# Resume support: don't create a second cancellation document if a prior
			# attempt already created one and failed at the posting step.
			object_id = (status.response_data or {}).get("ObjectID")
			if not object_id:
				response = rest_client.create_inbound_delivery_notification(cancel_payload)
				object_id = response.get("d", {}).get("results", {}).get("ObjectID")
				if not object_id:
					raise ValueError("ByD did not return ObjectID for cancellation.")
				# Persist BEFORE posting so a failed post resumes instead of re-creating.
				status.response_data = {"ObjectID": object_id, "stage": "created"}
				status.save(update_fields=['response_data', 'updated_at'])
				create_response = response
			else:
				create_response = {"resumed_with_object_id": object_id}

			time.sleep(5)

			post_response = rest_client.post_delivery_notification(object_id)

			status.mark_success({
				"ObjectID": object_id,
				"stage": "posted",
				"post_response": post_response,
			})

			# Keep bookkeeping that consumes the ByD responses inside the lock scope so
			# the variables are always bound; failures short-circuit straight to except.
			grn.inbound_delivery_metadata.setdefault("nullifications", []).append({
				"payload": cancel_payload,
				"create_response": create_response,
				"post_response": post_response,
				"posting_status_id": status.id,
				"cancelled_on": timezone.now().isoformat(),
			})
			grn.save(update_fields=['inbound_delivery_metadata'])
			grn.mark_nullified(reason="Admin-triggered nullification")

			return True

	except Exception as exc:
		status.mark_failure(str(exc))
		status.increment_retry()
		raise


def send_reset_link_to_user(args):
	user = args.get('user')
	token = args.get('token')
	if user.email:
		user_emails = [user.email]
		html_content = render_to_string('password_reset.html', {
			'reset_link': f"{os.getenv('VIMP_HOST')}/reset_password?token={token}&email={user.email}",
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
	
	verification_link = f'{os.getenv("VIMP_HOST")}/sign-up?{id_hash}={instance.token}'
	
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


def generate_weekly_report_task(week_start_date=None):
	"""
	Task to generate weekly reports automatically.
	This task can be scheduled to run at the end of each week (e.g., Sunday night or Monday morning).
	
	Args:
		week_start_date: Optional date string (YYYY-MM-DD) for the week to generate.
					   If not provided, generates report for the previous completed week.
	
	Returns:
		dict: Summary of the generated report or error details.
	"""
	from reports_service.views import calculate_weekly_report_data, get_week_boundaries
	from reports_service.models import WeeklyReport
	from datetime import datetime
	
	try:
		# Determine the week boundaries
		if week_start_date:
			if isinstance(week_start_date, str):
				week_start_date = datetime.strptime(week_start_date, '%Y-%m-%d').date()
			monday, sunday = get_week_boundaries(week_start_date)
		else:
			# Default to previous completed week
			monday, sunday = get_week_boundaries(previous_week=True)
		
		# Calculate ISO week info
		week_number = monday.isocalendar()[1]
		year = monday.isocalendar()[0]
		
		# Generate report data
		report_data = calculate_weekly_report_data(monday, sunday)
		
		# Save or update the report
		report, created = WeeklyReport.objects.update_or_create(
			year=year,
			week_number=week_number,
			defaults=report_data
		)
		
		# Return summary
		return {
			'success': True,
			'created': created,
			'report_id': report.id,
			'week_number': week_number,
			'year': year,
			'week_start': monday.isoformat(),
			'week_end': sunday.isoformat(),
			'summary': {
				'total_grns_received': report.total_grns_received,
				'total_gross_value_received': float(report.total_gross_value_received),
				'total_invoices_approved': report.total_invoices_approved,
				'total_approved_payment_value': float(report.total_approved_payment_value),
			}
		}
		
	except Exception as e:
		logger.error(f"Error generating weekly report: {e}")
		return {
			'success': False,
			'error': str(e)
		}


def send_weekly_report_email(report_id=None):
	"""
	Task to send weekly report summary via email to configured recipients.
	
	Args:
		report_id: Optional WeeklyReport ID. If not provided, sends the most recent report.
	
	Returns:
		bool: True if email sent successfully, False otherwise.
	"""
	from reports_service.models import WeeklyReport
	
	try:
		# Get the report
		if report_id:
			report = WeeklyReport.objects.get(id=report_id)
		else:
			report = WeeklyReport.objects.order_by('-year', '-week_number').first()
		
		if not report:
			logger.warning("No weekly report found to send.")
			return False
		
		# Prepare email content
		subject = f"Weekly Activity Report - Week {report.week_number}, {report.year}"
		
		html_content = f"""
		<html>
		<body style="font-family: Arial, sans-serif; padding: 20px;">
			<h1 style="color: #2957A4;">Weekly Activity Report</h1>
			<h2>Week {report.week_number}, {report.year}</h2>
			<p><strong>Period:</strong> {report.week_start_date} to {report.week_end_date}</p>
			
			<hr style="border: 1px solid #eee; margin: 20px 0;">
			
			<h3 style="color: #2957A4;">Goods Received Summary</h3>
			<table style="border-collapse: collapse; width: 100%; max-width: 500px;">
				<tr style="background-color: #f5f5f5;">
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Total GRNs Received</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.total_grns_received}</td>
				</tr>
				<tr>
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Line Items</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.total_grn_line_items}</td>
				</tr>
				<tr style="background-color: #f5f5f5;">
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Net Value</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">&#8358;{report.total_net_value_received:,.2f}</td>
				</tr>
				<tr>
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Gross Value</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">&#8358;{report.total_gross_value_received:,.2f}</td>
				</tr>
				<tr style="background-color: #f5f5f5;">
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Unique Vendors</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.unique_vendors_received}</td>
				</tr>
				<tr>
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Unique Stores</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.unique_stores_received}</td>
				</tr>
			</table>
			
			<h3 style="color: #2957A4; margin-top: 30px;">Vendor Payments Summary</h3>
			<table style="border-collapse: collapse; width: 100%; max-width: 500px;">
				<tr style="background-color: #f5f5f5;">
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Invoices Approved</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.total_invoices_approved}</td>
				</tr>
				<tr>
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Approved Value</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">&#8358;{report.total_approved_payment_value:,.2f}</td>
				</tr>
				<tr style="background-color: #f5f5f5;">
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Invoices Rejected</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.total_invoices_rejected}</td>
				</tr>
				<tr>
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Invoices Pending</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.total_invoices_pending}</td>
				</tr>
				<tr style="background-color: #f5f5f5;">
					<td style="padding: 10px; border: 1px solid #ddd;"><strong>Unique Vendors Paid</strong></td>
					<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{report.unique_vendors_paid}</td>
				</tr>
			</table>
			
			<hr style="border: 1px solid #eee; margin: 20px 0;">
			
			<p style="color: #666; font-size: 12px;">
				Report generated on {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC<br>
				This is an automated report from the VIMP system.
			</p>
		</body>
		</html>
		"""
		
		# Get recipients from environment or use default
		recipients = os.getenv('WEEKLY_REPORT_RECIPIENTS', os.getenv('TEST_EMAILS', '')).split(',')
		recipients = [r.strip() for r in recipients if r.strip()]
		
		if not recipients:
			logger.warning("No recipients configured for weekly report email.")
			return False
		
		# Send email
		email = EmailMessage(
			subject,
			html_content,
			'network@foodconceptsplc.com',
			recipients
		)
		email.content_subtype = 'html'
		email.send()
		
		logger.info(f"Weekly report email sent to {len(recipients)} recipients.")
		return True
		
	except Exception as e:
		logger.error(f"Error sending weekly report email: {e}")
		return False


if __name__ == "__main__":
	# from pprint import pprint
	# egrn = GoodsReceivedNote.objects.all().last()
	# send_grn_to_email(egrn)
	# invoice = Invoice.objects.get(id=323)
	# print(create_invoice_on_byd(invoice))
	...