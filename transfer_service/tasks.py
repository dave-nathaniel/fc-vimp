"""
Async tasks for transfer service
"""
import logging
import random
import string
import time

from django_q.tasks import async_task

from byd_service.models import get_or_create_byd_posting_status
from byd_service.rest import RESTServices

logger = logging.getLogger(__name__)


def post_goods_receipt_on_byd(receipt):
	"""
	Post a Goods Receipt on ByD for a completed transfer receipt.

	Two-step process:
	1. Create an Inbound Delivery Notification with received quantities
	2. Post the Goods Receipt to finalize it in ByD

	Args:
		receipt: TransferReceiptNote instance with line_items and inbound_delivery
	"""
	rest_client = RESTServices()

	# Generate a unique notification ID
	notification_id = f"TR{receipt.receipt_number}{''.join(random.choices(string.ascii_uppercase, k=2))}"

	# Build line items, extracting the SAP unit code from the original ByD metadata
	# (unit_of_measurement stores human-readable text like "Each", not the code "EA")
	items = []
	for index, line_item in enumerate(receipt.line_items.all()):
		metadata = line_item.inbound_delivery_line_item.metadata
		unit_code = (
			metadata.get("ItemDeliveryQuantity", {}).get("UnitCode", "")
			or metadata.get("QuantityUnitCode", "")
		)
		items.append({
			"ID": str(index + 1),
			"TypeCode": "14",
			"ProductID": line_item.inbound_delivery_line_item.product_id,
			"ItemDeliveryQuantity": {
				"Quantity": str(float(line_item.quantity_received)),
				"UnitCode": unit_code,
			},
		})

	payload = {
		"ID": notification_id,
		"ProcessingTypeCode": "SD",
		"Item": items,
		"SenderParty": {
			"PartyID": receipt.inbound_delivery.source_location_id
		},
		"ShipToParty": {
			"PartyID": receipt.inbound_delivery.destination_store.byd_cost_center_code
		},
	}

	status = get_or_create_byd_posting_status(
		receipt,
		request_payload=payload,
		task_name='transfer_service.tasks.post_goods_receipt_on_byd'
	)

	try:
		# Step 1: Create the inbound delivery notification
		response = rest_client.create_inbound_delivery_notification(payload)
		object_id = response.get("d", {}).get("results", {}).get("ObjectID")

		receipt.metadata.update({
			"byd_notification_id": notification_id,
			"byd_object_id": object_id,
			"create_response": response,
		})
		receipt.save(update_fields=['metadata'])

		# Step 2: Wait for ByD to index, then post the goods receipt
		time.sleep(5)

		post_response = rest_client.post_delivery_notification(object_id)
		receipt.metadata.update({
			"post_response": post_response,
		})
		receipt.save(update_fields=['metadata'])

		# Mark posting as successful
		status.mark_success(
			response.get("d", {}).get("results", {})
		)
		return True

	except Exception as e:
		logger.error(f"Error posting goods receipt for TR-{receipt.receipt_number}: {e}")
		status.mark_failure(str(e))
		status.increment_retry()

		# If locked by another process, re-queue for retry
		if "Object is locked" in str(e):
			async_task(
				'transfer_service.tasks.post_goods_receipt_on_byd',
				receipt,
				q_options={'task_name': f'Post-GoodsReceipt-TR-{receipt.receipt_number}-On-ByD-Retry'}
			)
		return False
